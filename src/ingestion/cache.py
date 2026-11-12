"""Extraction result caching module for P1 (Ingestion) (P1-13, P1-32, §6.4)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .models import Page

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("cache/extracted")
CACHE_VERSION = 1


def load_cache(
    doc_id: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> list[Page] | None:
    """Load cached extraction pages for doc_id (P1-13).

    Returns None if cache is missing, corrupted, or has an incompatible version.
    """
    path = Path(cache_dir) / f"{doc_id}.json"
    if not path.is_file():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return None

        # Version validation: if version does not match, trigger re-extraction
        if data.get("version") != CACHE_VERSION:
            return None

        raw_pages = data.get("pages")
        if not isinstance(raw_pages, list):
            return None

        pages: list[Page] = []
        for item in raw_pages:
            if not isinstance(item, dict) or "page" not in item or "text" not in item:
                return None
            pages.append(
                Page(
                    number=int(item["page"]),
                    text=str(item["text"]),
                    ocr=bool(item.get("ocr", False)),
                    confidence=(
                        float(item["confidence"]) if item.get("confidence") is not None else None
                    ),
                )
            )
        return pages
    except Exception as exc:
        logger.warning("Cache read failed for doc_id=%s: %s", doc_id, type(exc).__name__)
        return None


def save_cache(
    doc_id: str,
    pages: list[Page],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Path:
    """Atomically save extracted pages for doc_id to disk (P1-13).

    Writes to a temporary file in the same directory before atomically renaming,
    ensuring readers never observe partial files.
    """
    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{doc_id}.json"

    data = {
        "version": CACHE_VERSION,
        "pages": [
            {
                "page": p.number,
                "text": p.text,
                "ocr": p.ocr,
                "confidence": p.confidence,
            }
            for p in pages
        ],
    }

    # Write to a temporary file in the same directory for atomic replace
    temp_fd, temp_path_str = tempfile.mkstemp(dir=target_dir, prefix=f".{doc_id}_", suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path_str, target_file)
    except Exception:
        if os.path.exists(temp_path_str):
            os.unlink(temp_path_str)
        raise

    return target_file


def delete_cache(
    doc_id: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> None:
    """Idempotently delete cached extraction for doc_id (P1-32, §6.4)."""
    target_file = Path(cache_dir) / f"{doc_id}.json"
    try:
        target_file.unlink(missing_ok=True)
    except OSError:
        pass
