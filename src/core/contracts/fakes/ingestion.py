"""Fake implementation of the ``Ingestion`` Protocol (00-shared §6.2, §9; P1-ingestion §3.5, §8).

Provides ``FakeIngestion`` to allow P2, P3, P5, and P6 to run against the Ingestion contract
before the real extraction pipeline and OCR models are wired up.

Simulates document extraction by loading chunks from ``tests/fixtures/sample_chunks.jsonl``,
rewriting chunk fields to match the ingested document's identity and metadata, and cycling
through the status lifecycle:
    EXTRACTING -> CHUNKED -> index() -> INDEXED -> set_document_roles(doc_id, roles)

Log lines and error messages never contain document text or document titles.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from ..enums import DocStatus
from ..ids import make_chunk_id
from ..models import Chunk, DocumentMeta

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_CHUNKS_PATH = Path("tests/fixtures/sample_chunks.jsonl")
DEFAULT_EXTRACT_CACHE_DIR = Path("cache/extracted")


class FakeIngestion:
    """File-based fake of the ``Ingestion`` Protocol (00-shared §6.2, §9)."""

    def __init__(
        self,
        retrieval: Any | None = None,
        document_rights: Any | None = None,
        leak_index: Any | None = None,
        sample_chunks_path: Path | str | None = None,
        extract_cache_dir: Path | str = DEFAULT_EXTRACT_CACHE_DIR,
        chunk_limit: int | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._document_rights = document_rights
        self._leak_index = leak_index
        self._sample_chunks_path = Path(sample_chunks_path) if sample_chunks_path else None
        self._extract_cache_dir = Path(extract_cache_dir)
        self._chunk_limit = chunk_limit

    def _get_retrieval(self) -> Any:
        if self._retrieval is not None:
            return self._retrieval
        from ..registry import get_retrieval  # lazy import: registry.py does not exist yet

        return get_retrieval()

    def _get_document_rights(self) -> Any:
        if self._document_rights is not None:
            return self._document_rights
        from ..registry import get_document_rights  # lazy import

        return get_document_rights()

    def _get_leak_index(self) -> Any:
        if self._leak_index is not None:
            return self._leak_index
        try:
            from ..registry import get_leak_index  # lazy import

            return get_leak_index()
        except (ImportError, AttributeError):
            return None

    def _load_sample_chunks(self) -> list[Chunk]:
        path = self._sample_chunks_path or DEFAULT_SAMPLE_CHUNKS_PATH
        if not path.is_file():
            # If path is relative and not found in cwd, search relative to repo root
            root = Path(__file__).resolve().parents[4]
            alt = root / path
            if alt.is_file():
                path = alt

        chunks: list[Chunk] = []
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        chunks.append(Chunk.model_validate_json(line))
        return chunks

    def ingest(
        self,
        doc_id: str,
        file_path: Path,
        meta: DocumentMeta,
        roles: list[str],
        owner_id: UUID | None,
    ) -> None:
        """Simulates ingestion background process according to 00-shared §6.2 and §9.

        Extracts (from sample chunks) -> CHUNKED -> P2 index -> INDEXED -> set_document_roles.
        On any exception: set_status(failed, error) and stops.
        """
        rights = self._get_document_rights()
        retrieval = self._get_retrieval()
        leak = self._get_leak_index()

        try:
            rights.set_status(doc_id, DocStatus.EXTRACTING)

            raw_chunks = self._load_sample_chunks()
            if not raw_chunks:
                # Minimal fallback if fixture file is unavailable
                from src.ingestion.normalize import normalize_ar

                fallback_text = "نص تجريبي افتراضي."
                raw_chunks = [
                    Chunk(
                        chunk_id=make_chunk_id(doc_id, 0),
                        doc_id=doc_id,
                        chunk_index=0,
                        total_chunks=1,
                        text=fallback_text,
                        text_normalized=normalize_ar(fallback_text),
                        title=meta.title,
                        article=None,
                        hierarchy=[],
                        page_start=1,
                        page_end=1,
                        language="ar",
                        source_file=meta.source_file,
                        source=meta.source,
                        date=meta.date,
                        allowed_roles=[],
                        owner_id=owner_id,
                    )
                ]

            if self._chunk_limit is not None:
                raw_chunks = raw_chunks[: self._chunk_limit]

            total = len(raw_chunks)
            chunks: list[Chunk] = []
            for i, c in enumerate(raw_chunks):
                chunks.append(
                    Chunk(
                        chunk_id=make_chunk_id(doc_id, i),
                        doc_id=doc_id,
                        chunk_index=i,
                        total_chunks=total,
                        text=c.text,
                        text_normalized=c.text_normalized,
                        title=meta.title,
                        article=c.article,
                        hierarchy=list(c.hierarchy),
                        page_start=c.page_start,
                        page_end=c.page_end,
                        language=c.language,
                        source_file=meta.source_file,
                        source=meta.source,
                        date=meta.date,
                        allowed_roles=[],
                        owner_id=owner_id,
                    )
                )

            rights.set_status(doc_id, DocStatus.CHUNKED)

            retrieval.index(chunks)
            if leak is not None:
                full_text = "\n".join(c.text for c in chunks)
                leak.register(doc_id, full_text)

            rights.set_status(doc_id, DocStatus.INDEXED)
            rights.set_document_roles(doc_id, roles)
        except Exception as exc:
            logger.error(
                "FakeIngestion ingest failed",
                extra={"doc_id": doc_id, "error": type(exc).__name__},
            )
            try:
                rights.set_status(doc_id, DocStatus.FAILED, error=type(exc).__name__)
            except Exception:
                pass
            return

    def delete(self, doc_id: str) -> None:
        """Removes chunks from retrieval, fingerprints from leak index, and cache entry.

        Idempotent: deleting a missing document is never an error (P1-32).
        Never touches data/raw/.
        """
        retrieval = self._get_retrieval()
        retrieval.delete(doc_id)

        leak = self._get_leak_index()
        if leak is not None:
            try:
                leak.delete(doc_id)
            except Exception as exc:
                logger.warning(
                    "leak_index delete failed",
                    extra={"doc_id": doc_id, "error": type(exc).__name__},
                )

        cache_file = self._extract_cache_dir / f"{doc_id}.json"
        try:
            cache_file.unlink(missing_ok=True)
        except OSError:
            pass
