"""GatewayClient: LLMClient backed by the internal cloud gateway."""

import json
import logging
import os
from collections.abc import AsyncIterator

import httpx

from src.core.contracts.errors import ServiceError

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://cloud-gateway:8000"
DEFAULT_TIMEOUT_S = 120.0


class GatewayClient:
    """LLMClient that forwards requests to the internal cloud gateway."""

    def __init__(
        self,
        base_url: str = DEFAULT_GATEWAY_URL,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        from src.core.config import cfg

        if cfg.mode != "cloud" or os.environ.get("ALLOW_CLOUD_LLM") != "true":
            raise ServiceError("cloud mode not allowed")

        self.base_url = base_url
        self.timeout_s = timeout_s
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self.async_client = async_client

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        body: dict = {
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        try:
            response = self.client.post("/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            logger.error("cloud gateway unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("cloud gateway unavailable") from exc

        self._check(response.status_code)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ServiceError("cloud gateway gave an invalid answer") from exc

        if not isinstance(content, str):
            raise ServiceError("cloud gateway gave an invalid answer")
        return content

    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body: dict = {
            "messages": messages,
            "temperature": 0.0,
            "stream": True,
        }
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        client = self.async_client or httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_s
        )
        try:
            async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                self._check(response.status_code)
                completed = False
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        completed = True
                        break
                    try:
                        chunk = json.loads(data)
                        piece = chunk["choices"][0]["delta"].get("content") or ""
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise ServiceError("cloud gateway gave an invalid stream") from exc
                    if not isinstance(piece, str):
                        raise ServiceError("cloud gateway gave an invalid stream")
                    if piece:
                        yield piece

                if not completed:
                    raise ServiceError("cloud stream ended before completion")
        except httpx.HTTPError as exc:
            logger.error("cloud gateway unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("cloud gateway unavailable") from exc
        finally:
            if self.async_client is None:
                await client.aclose()

    def count_tokens(self, text: str) -> int:
        try:
            response = self.client.post("/count_tokens", json={"text": text})
        except httpx.HTTPError as exc:
            logger.error("cloud token counter unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("cloud token counter unavailable") from exc

        self._check(response.status_code)
        try:
            count = response.json()["count"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("cloud token counter gave an invalid answer") from exc

        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ServiceError("cloud token counter gave an invalid answer")
        return count

    @staticmethod
    def _check(status: int) -> None:
        if status >= 400:
            logger.error("cloud gateway refused request", extra={"status": status})
            raise ServiceError(f"cloud gateway refused the call ({status})")
