"""P6 model clients: the LLM (Ollama), the OCR service and the models service (P6 spec §3).

The three factories are what the registry calls when ``contracts.llm``, ``contracts.ocr`` or
``contracts.models`` is ``real``. Each client lives in its own module and is imported inside its
factory, so one client can be merged and used without the others being there yet.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import HttpModelsClient
    from .ocr import HttpOCRClient
    from .ollama import OllamaClient

__all__ = ["real_llm", "real_models", "real_ocr"]


def real_llm() -> "OllamaClient":
    """The real ``LLMClient``: Ollama, with the context window set by ``llm.num_ctx``.

    In ``light`` mode it serves ``llm.model_light``, otherwise ``llm.model`` (P6 spec §6.2). In
    ``cloud`` mode it is a ``GatewayClient``, which raises ``ServiceError`` unless
    ``ALLOW_CLOUD_LLM=true`` (P6-14); the narration model stays on the local Ollama.
    """
    from src.core.config import cfg  # imported here: loading the config needs the full .env

    from .ollama import OllamaClient

    if cfg.mode == "cloud":
        from .gateway import GatewayClient

        local = OllamaClient(
            cfg.llm.base_url, model=cfg.llm.narration_model, num_ctx=cfg.llm.num_ctx
        )
        return GatewayClient(
            cfg.mode,
            model=cfg.llm.model,
            num_ctx=cfg.llm.num_ctx,
            local=local,
            narration_model=cfg.llm.narration_model,
        )
    model = cfg.llm.model_light if cfg.mode == "light" else cfg.llm.model
    return OllamaClient(cfg.llm.base_url, model=model, num_ctx=cfg.llm.num_ctx)


def real_ocr() -> "HttpOCRClient":
    """The real ``OCRClient``: the ``ocr`` service."""
    from src.core.config import cfg

    from .ocr import HttpOCRClient

    return HttpOCRClient(cfg.ocr.base_url)


def real_models() -> "HttpModelsClient":
    """The real ``ModelsClient``: the ``models`` service (bge-m3 and the re-ranker)."""
    from src.core.config import cfg

    from .models import HttpModelsClient

    return HttpModelsClient(cfg.models.base_url)
