"""Ingestion pipeline implementation (P1-27 à P1-32, §6.1, §6.4, §7)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from src.core.contracts.enums import AuditAction, DocStatus
from src.core.contracts.errors import InvalidInput
from src.core.contracts.ids import make_content_hash
from src.core.contracts.models import DocumentMeta
from src.ingestion.cache import DEFAULT_CACHE_DIR, delete_cache, load_cache, save_cache
from src.ingestion.chunking import chunk_document
from src.ingestion.extract import extract
from src.ingestion.normalize import normalize_ar

if TYPE_CHECKING:
    from src.core.contracts.protocols import Audit, DocumentRights, LeakIndex, OCRClient, Retrieval

logger = logging.getLogger(__name__)

SPEC_ERRORS: frozenset[str] = frozenset(
    {
        "unsupported format",
        "cannot open file",
        "too many scanned pages",
        "OCR quality too low",
        "no text extracted",
    }
)


def short_reason(exc: Exception) -> str:
    """Return sanitized short reason without document text (P1-30, §7, T18)."""
    msg = str(exc)
    if isinstance(exc, InvalidInput) and msg in SPEC_ERRORS:
        return msg
    return type(exc).__name__


class IngestionPipeline:
    """Full background ingestion pipeline implementing the Ingestion Protocol."""

    def __init__(
        self,
        rights: DocumentRights | None = None,
        retrieval: Retrieval | None = None,
        leak: LeakIndex | None = None,
        audit: Audit | None = None,
        ocr: OCRClient | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        if rights is not None:
            self.rights = rights
        else:
            from src.core.contracts.registry import get_document_rights

            self.rights = get_document_rights()

        if retrieval is not None:
            self.retrieval = retrieval
        else:
            from src.core.contracts.registry import get_retrieval

            self.retrieval = get_retrieval()

        if leak is not None:
            self.leak = leak
        else:
            from src.core.contracts.registry import get_leak_index

            self.leak = get_leak_index()

        if audit is not None:
            self.audit = audit
        else:
            from src.core.contracts.registry import get_audit

            self.audit = get_audit()

        if ocr is not None:
            self.ocr = ocr
        else:
            from src.core.contracts.registry import get_ocr

            self.ocr = get_ocr()

        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR

    def ingest(
        self,
        doc_id: str,
        file_path: Path,
        meta: DocumentMeta,
        roles: list[str],
        owner_id: UUID | None,
    ) -> None:
        """Execute ingestion workflow (§6.1, P1-27 à P1-31)."""
        path = Path(file_path)

        # Detect retry BEFORE modifying any status (P1-28, §6.1)
        is_retry = False
        try:
            is_retry = self.rights.get_status(doc_id) == DocStatus.FAILED
        except Exception:
            is_retry = False

        try:
            self.rights.set_status(doc_id, DocStatus.EXTRACTING)
            if is_retry:
                self.retrieval.delete(doc_id)
                self.leak.delete(doc_id)

            pages = load_cache(doc_id, cache_dir=self.cache_dir)
            if pages is None:
                pages = extract(path, owner_id=owner_id, ocr_client=self.ocr)
                save_cache(doc_id, pages, cache_dir=self.cache_dir)

            full_text = "\n".join(p.text for p in pages)
            normalized_text = normalize_ar(full_text)
            self.rights.set_content_hash(doc_id, make_content_hash(normalized_text))

            chunks = chunk_document(doc_id, pages, owner_id=owner_id, meta=meta)
            if not chunks:
                raise InvalidInput("no text extracted")

            self.rights.set_status(doc_id, DocStatus.CHUNKED)
            self.retrieval.index(chunks)
            self.leak.register(doc_id, full_text)
            self.rights.set_status(doc_id, DocStatus.INDEXED)
        except Exception as e:
            reason = short_reason(e)
            self.rights.set_status(doc_id, DocStatus.FAILED, error=reason)
            self.audit.log_action(
                None,
                AuditAction.INGEST_FAILED,
                {"doc_id": doc_id, "reason": reason},
            )
            return

        try:
            self.rights.set_document_roles(doc_id, roles)
        except Exception as e:
            # P5 has already set FAILED, kept the document hidden and logged it
            logger.warning(
                "publication failed: doc_id=%s reason=%s",
                doc_id,
                short_reason(e),
            )

    def delete(self, doc_id: str) -> None:
        """Idempotent deletion delegating to P2, P6, and local cache (§6.4, P1-32)."""
        self.retrieval.delete(doc_id)
        self.leak.delete(doc_id)
        delete_cache(doc_id, cache_dir=self.cache_dir)
