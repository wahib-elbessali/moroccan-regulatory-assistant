"""P6 model clients: LLM, OCR and models service."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.contracts.protocols import LLMClient

    from .models import HttpModelsClient
    from .ocr import HttpOCRClient

__all__ = ["real_llm", "real_models", "real_ocr"]


def real_llm() -> "LLMClient":
    """Return the real LLM client selected by the application mode."""
    from src.core.config import cfg

    if cfg.mode == "cloud":
        from .gateway import GatewayClient

        return GatewayClient()

    from .ollama import OllamaClient

    model = cfg.llm.model_light if cfg.mode == "light" else cfg.llm.model
    return OllamaClient(cfg.llm.base_url, model=model, num_ctx=cfg.llm.num_ctx)


def real_ocr() -> "HttpOCRClient":
    """The real OCRClient: the OCR service."""
    from src.core.config import cfg

    from .ocr import HttpOCRClient

    return HttpOCRClient(cfg.ocr.base_url)


def real_models() -> "HttpModelsClient":
    """The real ModelsClient: the models service."""
    from src.core.config import cfg

    from .models import HttpModelsClient

    return HttpModelsClient(cfg.models.base_url)
