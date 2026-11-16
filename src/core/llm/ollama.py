"""``OllamaClient``: the real ``LLMClient``, backed by the ``llm`` service (P6-08, P6-11).

Every call passes ``llm.num_ctx`` as ``options.num_ctx`` (P6-08): Ollama's default context is too
small for the Rédacteur's prompt and would cut it silently. ``temperature`` is 0.0 by default and
``max_tokens`` becomes ``options.num_predict`` (P6-15).

``count_tokens`` uses the Qwen tokenizer downloaded by ``make models`` (P6-16), loaded the first
time it is needed, so ``chat`` and ``stream`` work even where the tokenizer files are missing.

Prompts hold document passages, so nothing of a message or an answer is ever logged.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from tokenizers import Tokenizer

from src.core.contracts.errors import ServiceError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 300.0  # a long answer from the 7B model on CPU can take minutes
TOKENIZER_REPO = "Qwen/Qwen2.5-7B-Instruct"  # services/download_models.py; the family shares it
HF_HOME_ENV = "HF_HOME"
DEFAULT_HF_HOME = "/hf"  # where docker-compose.yml mounts the hf_cache volume in api


def find_tokenizer(hf_home: str | Path | None = None) -> Path:
    """The Qwen ``tokenizer.json`` in the Hugging Face cache filled by ``make models``.

    Raises:
        ServiceError: The file is not there (``make models`` has not run).
    """
    home = Path(hf_home or os.environ.get(HF_HOME_ENV) or DEFAULT_HF_HOME)
    snapshots = home / "hub" / ("models--" + TOKENIZER_REPO.replace("/", "--")) / "snapshots"
    found = sorted(snapshots.glob("*/tokenizer.json"))
    if not found:
        raise ServiceError("Qwen tokenizer not found (run `make models`)")
    return found[-1]


class OllamaClient:
    """``LLMClient`` that calls Ollama's ``/api/chat``.

    Args:
        base_url: The ``llm`` service (``llm.base_url``).
        model: The default model (``llm.model``); each call can name another one.
        num_ctx: The context window passed on every call (``llm.num_ctx``).
        timeout_s: Seconds before a call gives up.
        tokenizer_path: The Qwen ``tokenizer.json``; found in the Hugging Face cache if ``None``.
        client: An ``httpx.Client`` for ``chat``; tests pass one with a mock transport.
        async_client: An ``httpx.AsyncClient`` for ``stream``; same.
    """

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        num_ctx: int,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        tokenizer_path: str | Path | None = None,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if num_ctx < 1:
            raise ValueError("num_ctx must be at least 1")
        self.base_url = base_url
        self.model = model
        self.num_ctx = num_ctx
        self.timeout_s = timeout_s
        self.tokenizer_path = tokenizer_path
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self.async_client = async_client
        self._tokenizer: Tokenizer | None = None

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """The model's whole answer.

        Raises:
            ServiceError: Ollama is unreachable, refused the call, or gave a bad answer.
        """
        body = self._body(messages, model, max_tokens, temperature, stream=False)
        try:
            response = self.client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            logger.error("llm unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("llm service unavailable") from exc
        self._check(response.status_code)
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("llm service gave an invalid answer") from exc
        if not isinstance(content, str):
            raise ServiceError("llm service gave an invalid answer")
        return content

    async def stream(
        self, messages: list[dict], *, model: str | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """The model's answer, piece by piece, as Ollama writes it.

        Raises:
            ServiceError: Ollama is unreachable, refused the call, or broke off mid-answer.
        """
        body = self._body(messages, model, max_tokens, 0.0, stream=True)
        client = self.async_client or httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_s
        )
        try:
            async with client.stream("POST", "/api/chat", json=body) as response:
                self._check(response.status_code)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    piece, done = self._parse_line(line)
                    if piece:
                        yield piece
                    if done:
                        return
            raise ServiceError("llm stream ended before the answer was complete")
        except httpx.HTTPError as exc:
            logger.error("llm unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("llm service unavailable") from exc
        finally:
            if self.async_client is None:
                await client.aclose()

    def count_tokens(self, text: str) -> int:
        """Tokens of ``text`` for the Qwen 2.5 tokenizer (P6-16), not a word count.

        Raises:
            ServiceError: The tokenizer files are missing (``make models`` has not run).
        """
        if self._tokenizer is None:
            path = Path(self.tokenizer_path) if self.tokenizer_path else find_tokenizer()
            try:
                self._tokenizer = Tokenizer.from_file(str(path))
            except Exception as exc:  # the tokenizers library raises its own exception type
                raise ServiceError("Qwen tokenizer could not be loaded") from exc
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def _body(
        self,
        messages: list[dict],
        model: str | None,
        max_tokens: int | None,
        temperature: float,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"num_ctx": self.num_ctx, "temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        return {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }

    @staticmethod
    def _check(status: int) -> None:
        if status >= 400:
            logger.error("llm refused", extra={"status": status})
            raise ServiceError(f"llm service refused the call ({status})")

    @staticmethod
    def _parse_line(line: str) -> tuple[str, bool]:
        """One line of Ollama's stream: the text piece and whether the answer is complete."""
        try:
            chunk = json.loads(line)
        except ValueError as exc:
            raise ServiceError("llm service gave an invalid answer") from exc
        if not isinstance(chunk, dict) or "error" in chunk:
            raise ServiceError("llm service failed mid-answer")
        message = chunk.get("message") or {}
        piece = message.get("content", "") if isinstance(message, dict) else ""
        return (piece if isinstance(piece, str) else ""), bool(chunk.get("done"))
