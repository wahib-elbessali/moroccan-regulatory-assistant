"""Tests for extraction cache module (P1-13, P1-32, T11, T16, T17)."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.cache import delete_cache, load_cache, save_cache
from src.ingestion.models import Page


def test_save_and_load_cache(tmp_path: Path) -> None:
    """Cache correctly stores pages with 'version': 2 and loads them identically."""
    doc_id = "test_doc_001"
    pages = [
        Page(number=1, text="Page 1 text", ocr=False, confidence=None),
        Page(number=2, text="Page 2 text", ocr=True, confidence=0.85),
    ]

    saved_path = save_cache(doc_id, pages, cache_dir=tmp_path)
    assert saved_path.is_file()

    # Verify JSON structure
    with open(saved_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 2
    assert len(data["pages"]) == 2
    assert data["pages"][0]["page"] == 1
    assert data["pages"][0]["text"] == "Page 1 text"
    assert data["pages"][0]["ocr"] is False
    assert data["pages"][0]["confidence"] is None
    assert data["pages"][1]["confidence"] == 0.85

    # Reload through load_cache
    loaded = load_cache(doc_id, cache_dir=tmp_path)
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0].number == 1
    assert loaded[0].text == "Page 1 text"
    assert loaded[1].number == 2
    assert loaded[1].ocr is True
    assert loaded[1].confidence == 0.85


def test_load_cache_missing_returns_none(tmp_path: Path) -> None:
    """Non-existent cache file returns None without error."""
    assert load_cache("missing_doc", cache_dir=tmp_path) is None


def test_load_cache_corrupt_returns_none(tmp_path: Path) -> None:
    """Corrupted JSON returns None and triggers re-extraction."""
    corrupt_file = tmp_path / "corrupt_doc.json"
    corrupt_file.write_text("{invalid json", encoding="utf-8")

    assert load_cache("corrupt_doc", cache_dir=tmp_path) is None


def test_load_cache_incompatible_version_returns_none(tmp_path: Path) -> None:
    """Cache file with incompatible schema version triggers re-extraction."""
    file_path = tmp_path / "old_doc.json"
    file_path.write_text(json.dumps({"version": 99, "pages": []}), encoding="utf-8")

    assert load_cache("old_doc", cache_dir=tmp_path) is None


def test_delete_cache_idempotent(tmp_path: Path) -> None:
    """Deleting an existing cache removes it; deleting twice raises no error (P1-32, T16)."""
    doc_id = "to_delete"
    pages = [Page(number=1, text="Text")]
    save_cache(doc_id, pages, cache_dir=tmp_path)

    cache_file = tmp_path / f"{doc_id}.json"
    assert cache_file.is_file()

    delete_cache(doc_id, cache_dir=tmp_path)
    assert not cache_file.is_file()

    # Second delete is a no-op (idempotent)
    delete_cache(doc_id, cache_dir=tmp_path)


def test_t17_cache_isolation_per_doc_id(tmp_path: Path) -> None:
    """T17: Cache is strictly partitioned per doc_id and never shared."""
    doc_id_user1 = "doc_sha_user_1"
    doc_id_user2 = "doc_sha_user_2"

    pages1 = [Page(number=1, text="User 1 text", ocr=True, confidence=0.9)]
    save_cache(doc_id_user1, pages1, cache_dir=tmp_path)

    assert load_cache(doc_id_user1, cache_dir=tmp_path) is not None
    assert load_cache(doc_id_user2, cache_dir=tmp_path) is None
