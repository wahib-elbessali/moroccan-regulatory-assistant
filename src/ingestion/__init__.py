"""Ingestion package (P1)."""

from typing import Any

from .normalize import normalize_ar


def real_ingestion(
    rights: Any = None,
    retrieval: Any = None,
    leak: Any = None,
    audit: Any = None,
    ocr: Any = None,
    cache_dir: Any = None,
    **collaborateurs: Any,
) -> Any:
    """Factory returning an IngestionProtocol implementation (00-shared §9).

    Heavy imports are kept inside this function.
    """
    from .pipeline import IngestionPipeline

    return IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=cache_dir,
        **collaborateurs,
    )


__all__ = ["normalize_ar", "real_ingestion"]
