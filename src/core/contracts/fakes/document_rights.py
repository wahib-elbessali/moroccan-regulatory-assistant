"""
src/core/contracts/fakes/document_rights.py
In-memory fake implementation of DocumentRightsProtocol (P5 contract).
Used for isolated cross-part tests (P1, P3, P6).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.contracts.errors import Conflict, InvalidInput, NotFound
from src.core.contracts.ids import make_doc_id
from src.core.contracts.models import DocumentMeta


class FakeDocumentRights:
    """In-memory fake implementation of DocumentRightsProtocol."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []

    def create_document(
        self,
        data: bytes,
        file_name: str,
        meta: DocumentMeta,
        owner_id: UUID | None,
        uploaded_by: UUID,
    ) -> tuple[str, Path]:
        doc_id = make_doc_id(data, owner_id)
        if doc_id in self.documents:
            raise Conflict("already uploaded")

        path = Path(f"storage/uploads/{doc_id}.bin")
        self.documents[doc_id] = {
            "id": doc_id,
            "title": meta.title,
            "source_file": file_name,
            "source": meta.source,
            "date": meta.date,
            "owner_id": owner_id,
            "status": "received",
            "roles": [],
            "content_hash": None,
            "created_at": datetime.now(UTC),
        }
        self.history.append({"action": "create", "doc_id": doc_id})
        return doc_id, path

    def get_status(self, doc_id: str) -> str:
        if doc_id not in self.documents:
            raise NotFound("document not found")
        return self.documents[doc_id]["status"]

    def set_status(self, doc_id: str, status: str, error: str | None = None) -> None:
        if doc_id not in self.documents:
            raise NotFound("document not found")
        self.documents[doc_id]["status"] = status
        self.documents[doc_id]["error"] = error
        self.history.append({"action": "set_status", "doc_id": doc_id, "status": status})

    def set_content_hash(self, doc_id: str, content_hash: str) -> None:
        if doc_id not in self.documents:
            raise NotFound("document not found")
        self.documents[doc_id]["content_hash"] = content_hash
        self.history.append({"action": "set_content_hash", "doc_id": doc_id, "hash": content_hash})

    def set_document_roles(self, doc_id: str, roles: list[str]) -> dict[str, Any]:
        if doc_id not in self.documents:
            raise NotFound("document not found")
        current_status = self.documents[doc_id]["status"]
        if current_status not in ("indexed", "ready"):
            raise InvalidInput("document is not indexed")

        self.documents[doc_id]["roles"] = list(roles)
        self.documents[doc_id]["status"] = "ready"
        self.history.append({"action": "set_roles", "doc_id": doc_id, "roles": roles})
        return {"doc_id": doc_id, "status": "ready"}
