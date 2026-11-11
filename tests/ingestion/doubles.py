"""Test doubles and fixed UUIDs for P1 ingestion tests (00-shared §9; P1-ingestion §8)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.core.contracts import Chunk, DocStatus

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
        self.indexed_chunks.extend(chunks)

    def delete(self, doc_id: str) -> None:
        """Records document deletion and cleans up internal storage."""
        self.delete_calls.append(doc_id)
        self.indexed_chunks = [c for c in self.indexed_chunks if c.doc_id != doc_id]


class RecordingDocumentRights:
    """A test double for DocumentRights recording status transitions and role updates."""

    def __init__(self, initial_status: str = DocStatus.RECEIVED) -> None:
        self.statuses: dict[str, str] = {}
        self.status_history: list[tuple[str, str, str | None]] = []
        self.roles_set: list[tuple[str, list[str]]] = []
        self.content_hashes: dict[str, str] = {}
        self._default_status = initial_status

    def set_status(self, doc_id: str, status: str, error: str | None = None) -> None:
        """Records a status transition."""
        self.statuses[doc_id] = status
        self.status_history.append((doc_id, status, error))

    def get_status(self, doc_id: str) -> str:
        """Returns the current document status."""
        return self.statuses.get(doc_id, self._default_status)

    def set_document_roles(self, doc_id: str, roles: list[str]) -> dict[str, Any]:
        """Records roles applied to a document."""
        self.roles_set.append((doc_id, list(roles)))
        return {"doc_id": doc_id, "roles": list(roles)}

    def set_content_hash(self, doc_id: str, content_hash: str) -> None:
        """Records the document full-text content hash."""
        self.content_hashes[doc_id] = content_hash


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
