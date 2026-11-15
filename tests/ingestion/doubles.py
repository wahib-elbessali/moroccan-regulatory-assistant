"""Test doubles and fixed UUIDs for P1 ingestion tests (00-shared §9; P1-ingestion §8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.contracts import Chunk, DocStatus, DocumentMeta

# must stay identical to tests/conftest.py (P5-08)
LECTEUR_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_LECTEUR_ID = UUID("44444444-4444-4444-4444-444444444444")


class RecordingRetrieval:
    """A test double for the Retrieval protocol that records index and delete calls."""

    def __init__(self, *, fail_index: Exception | None = None) -> None:
        self.indexed_chunks: list[Chunk] = []
        self.index_calls: list[list[Chunk]] = []
        self.delete_calls: list[str] = []
        self.fail_index = fail_index

    def index(self, chunks: list[Chunk]) -> None:
        """Records indexed chunks or simulates an indexing error."""
        if self.fail_index is not None:
            raise self.fail_index
        self.index_calls.append(list(chunks))
        if chunks:
            doc_id = chunks[0].doc_id
            total = chunks[0].total_chunks
            new_by_id = {c.chunk_id: c for c in chunks}
            kept = [
                c
                for c in self.indexed_chunks
                if c.doc_id != doc_id or (c.chunk_id not in new_by_id and c.chunk_index < total)
            ]
            self.indexed_chunks = kept + list(new_by_id.values())
        else:
            self.indexed_chunks.extend(chunks)

    def delete(self, doc_id: str) -> None:
        """Records document deletion and cleans up internal storage."""
        self.delete_calls.append(doc_id)
        self.indexed_chunks = [c for c in self.indexed_chunks if c.doc_id != doc_id]


class RecordingDocumentRights:
    """A test double for DocumentRights recording status transitions and role updates."""

    def __init__(
        self,
        initial_status: str = DocStatus.RECEIVED,
        fail_set_roles: Exception | None = None,
    ) -> None:
        self.statuses: dict[str, str] = {}
        self.status_history: list[tuple[str, str, str | None]] = []
        self.roles_set: list[tuple[str, list[str]]] = []
        self.content_hashes: dict[str, str] = {}
        self.created_docs: list[tuple[str, str, DocumentMeta, UUID | None, UUID | None]] = []
        self._default_status = initial_status
        self.fail_set_roles = fail_set_roles

    def create_document(
        self,
        file_bytes: bytes,
        file_name: str,
        meta: DocumentMeta,
        owner_id: UUID | None,
        uploaded_by: UUID | None = None,
    ) -> tuple[str, Path]:
        from src.core.contracts.errors import Conflict
        from src.core.contracts.ids import make_doc_id

        doc_id = make_doc_id(file_bytes, owner_id)
        if doc_id in self.statuses:
            raise Conflict("already uploaded")
        self.statuses[doc_id] = DocStatus.RECEIVED
        self.created_docs.append((doc_id, file_name, meta, owner_id, uploaded_by))
        path = Path(f"storage/uploads/{doc_id}.bin")
        return doc_id, path

    def set_status(self, doc_id: str, status: str, error: str | None = None) -> None:
        """Records a status transition."""
        self.statuses[doc_id] = status
        self.status_history.append((doc_id, status, error))

    def get_status(self, doc_id: str) -> str:
        """Returns the current document status."""
        return self.statuses.get(doc_id, self._default_status)

    def set_document_roles(self, doc_id: str, roles: list[str]) -> dict[str, Any]:
        """Records roles applied to a document."""
        if self.fail_set_roles is not None:
            raise self.fail_set_roles
        self.roles_set.append((doc_id, list(roles)))
        return {"doc_id": doc_id, "roles": list(roles)}

    def set_content_hash(self, doc_id: str, content_hash: str) -> None:
        """Records the document full-text content hash."""
        self.content_hashes[doc_id] = content_hash


class RecordingAudit:
    """A test double for the Audit protocol recording log_action and log_query."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []

    def log_action(
        self,
        user_id: UUID | None,
        action_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.actions.append(
            {
                "user_id": user_id,
                "action_type": action_type,
                "details": details or {},
            }
        )

    def log_query(
        self,
        request_id: UUID,
        user_id: UUID | None,
        query: str,
        latency_ms: int,
    ) -> None:
        self.queries.append(
            {
                "request_id": request_id,
                "user_id": user_id,
                "query": query,
                "latency_ms": latency_ms,
            }
        )


class RecordingLeakIndex:
    """A test double for LeakIndex recording registration and deletion."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    def register(self, doc_id: str, full_text: str) -> None:
        """Records document full-text registration."""
        self.registered.append((doc_id, full_text))

    def delete(self, doc_id: str) -> None:
        """Records leak index deletion."""
        self.delete_calls.append(doc_id)


class ScriptedOCRClient:
    """A test double for OCRClient recording calls and returning scripted responses."""

    def __init__(
        self,
        default_text: str = "نص مستخرج بالتعرف الضوئي",
        default_confidence: float = 0.9,
        responses: list[tuple[str, float]] | None = None,
    ) -> None:
        self.call_count: int = 0
        self.calls: list[tuple[bytes, str]] = []
        self.default_text = default_text
        self.default_confidence = default_confidence
        self._responses = list(responses) if responses else []

    def ocr_page(self, image: bytes, lang: str = "ar") -> tuple[str, float]:
        self.call_count += 1
        self.calls.append((image, lang))
        if self._responses:
            return self._responses.pop(0)
        return self.default_text, self.default_confidence


class RecordingIngestion:
    """A test double for Ingestion recording ingest and delete calls."""

    def __init__(
        self,
        document_rights: RecordingDocumentRights | None = None,
        fail_doc_ids: set[str] | None = None,
    ) -> None:
        self.rights = document_rights
        self.ingest_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []
        self.fail_doc_ids = set(fail_doc_ids or [])

    def ingest(
        self,
        doc_id: str,
        file_path: Path,
        meta: DocumentMeta,
        roles: list[str],
        owner_id: UUID | None,
    ) -> None:
        self.ingest_calls.append(
            {
                "doc_id": doc_id,
                "file_path": Path(file_path),
                "meta": meta,
                "roles": list(roles),
                "owner_id": owner_id,
            }
        )
        if self.rights is not None:
            if doc_id in self.fail_doc_ids:
                self.rights.set_status(doc_id, DocStatus.FAILED, error="simulated failure")
            else:
                self.rights.set_status(doc_id, DocStatus.READY)

    def delete(self, doc_id: str) -> None:
        self.delete_calls.append(doc_id)
