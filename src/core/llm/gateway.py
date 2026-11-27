"""``GatewayClient`` and ``GatewayOCRClient``: the clients of ``cloud`` mode (P6-11, P6-12, P6-14).

``cloud`` mode is for development only: the demo and every evaluation run locally, offline. So the
client refuses to exist unless both switches are on, ``mode: cloud`` in ``config.yaml`` **and**
``ALLOW_CLOUD_LLM=true`` in ``.env``. One of them alone is not enough, so a forgotten variable or a
wrong mode can never send a prompt (which holds document passages) out of the machine.

``cloud-gateway`` is the only service besides ``web-search`` and ``searxng`` on the ``egress``
network. It speaks Ollama's ``/api/chat``, so this client reuses ``OllamaClient``; the gateway
maps the request to the cloud provider. ``count_tokens`` still counts with the Qwen tokenizer: an
estimate when the cloud model is another family.
"""

import os
from pathlib import Path

import httpx

from src.core.contracts.errors import ServiceError

from .ocr import DEFAULT_TIMEOUT_S as OCR_TIMEOUT_S
from .ocr import HttpOCRClient
from .ollama import DEFAULT_TIMEOUT_S, OllamaClient

ALLOW_ENV = "ALLOW_CLOUD_LLM"
GATEWAY_URL = "http://cloud-gateway:8000"  # P6 spec §6.1
NOT_ALLOWED = "cloud mode not allowed"


def cloud_allowed(mode: str, environ: dict[str, str] | None = None) -> bool:
    """``True`` only when ``mode`` is ``cloud`` and ``ALLOW_CLOUD_LLM`` is ``true``."""
    env = os.environ if environ is None else environ
    return mode == "cloud" and env.get(ALLOW_ENV, "").strip().lower() == "true"


class GatewayClient(OllamaClient):
    """``LLMClient`` that sends every call to ``cloud-gateway``.

    Args:
        mode: ``config.yaml``'s ``mode``.
        model: The model name passed to the gateway (``llm.model``).
        num_ctx: The context window passed on every call (``llm.num_ctx``).
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


class GatewayOCRClient(HttpOCRClient):
    """``OCRClient`` that sends a page to ``cloud-gateway`` (P6-12, cloud fallback; P6-14 lock).

    Not used by ``real_ocr``: OCR stays local in every mode. ``cloud-gateway`` answers its
    ``/ocr`` with 501 until a cloud OCR provider is wired, which this client turns into
    ``ServiceError`` like any refusal.

    Raises:
        ServiceError: ``cloud mode not allowed``, unless ``cloud_allowed`` (P6-14).
    """

    def __init__(
        self,
        mode: str,
        *,
        base_url: str = GATEWAY_URL,
        environ: dict[str, str] | None = None,
        timeout_s: float = OCR_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        if not cloud_allowed(mode, environ):
            raise ServiceError(NOT_ALLOWED)
        super().__init__(base_url, timeout_s=timeout_s, client=client)
