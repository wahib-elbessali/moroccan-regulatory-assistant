"""``GatewayClient``: the ``LLMClient`` of ``cloud`` mode, through ``cloud-gateway`` (P6-11, P6-14).

``cloud`` mode compares the local model with a cloud one, in the evaluation and in the demo. Only
the answer model goes to the cloud: the narration model stays on the local Ollama, and so do the
embeddings, the re-ranker and the OCR, which never use this client.

The client refuses to exist unless both switches are on, ``mode: cloud`` in ``config.yaml``
**and** ``ALLOW_CLOUD_LLM=true`` in ``.env``. One of them alone is not enough, so a forgotten
variable or a wrong mode can never send a prompt (which holds document passages) out of the
machine.

``cloud-gateway`` is the only service besides ``web-search`` and ``searxng`` on the ``egress``
network, and the only one that holds the provider's key. It speaks Ollama's ``/api/chat``, so
this client reuses ``OllamaClient``. ``count_tokens`` counts with the Qwen tokenizer: an estimate
when the cloud model is another family.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from src.core.contracts.errors import ServiceError

from .ollama import DEFAULT_TIMEOUT_S, OllamaClient

ALLOW_ENV = "ALLOW_CLOUD_LLM"
GATEWAY_URL = "http://cloud-gateway:8000"  # P6 spec §6.1
NOT_ALLOWED = "cloud mode not allowed"


def cloud_allowed(mode: str, environ: dict[str, str] | None = None) -> bool:
    """``True`` only when ``mode`` is ``cloud`` and ``ALLOW_CLOUD_LLM`` is ``true``."""
    env = os.environ if environ is None else environ
    return mode == "cloud" and env.get(ALLOW_ENV, "").strip().lower() == "true"


class GatewayClient(OllamaClient):
    """``LLMClient`` that sends the answer model's calls to ``cloud-gateway``.

    A call that names ``narration_model`` goes to ``local`` instead, the local Ollama.

    Args:
        mode: ``config.yaml``'s ``mode``.
        model: The answer model's name (``llm.model``); the gateway replaces it with the
            provider's model.
        num_ctx: The context window passed on every call (``llm.num_ctx``).
        local: The local Ollama client used for the narration model.
        narration_model: ``llm.narration_model``.
        base_url: The gateway; tests pass another one.
        environ: The environment to read ``ALLOW_CLOUD_LLM`` from; ``os.environ`` if ``None``.
        timeout_s, tokenizer_path, client, async_client: As for ``OllamaClient``.

    Raises:
        ServiceError: ``cloud mode not allowed``, unless ``cloud_allowed`` (P6-14, T14).
    """

    def __init__(
        self,
        mode: str,
        *,
        model: str,
        num_ctx: int,
        local: OllamaClient | None = None,
        narration_model: str | None = None,
        base_url: str = GATEWAY_URL,
        environ: dict[str, str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        tokenizer_path: str | Path | None = None,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not cloud_allowed(mode, environ):
            raise ServiceError(NOT_ALLOWED)
        super().__init__(
            base_url,
            model=model,
            num_ctx=num_ctx,
            timeout_s=timeout_s,
            tokenizer_path=tokenizer_path,
            client=client,
            async_client=async_client,
        )
        self.local = local
        self.narration_model = narration_model

    def _stays_local(self, model: str | None) -> bool:
        return self.local is not None and model is not None and model == self.narration_model

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        if self._stays_local(model):
            assert self.local is not None
            return self.local.chat(
                messages, model=model, max_tokens=max_tokens, temperature=temperature
            )
        return super().chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)

    async def stream(
        self, messages: list[dict], *, model: str | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        target = self.local if self._stays_local(model) else None
        source = (
            target.stream(messages, model=model, max_tokens=max_tokens)
            if target is not None
            else super().stream(messages, model=model, max_tokens=max_tokens)
        )
        async for piece in source:
            yield piece
