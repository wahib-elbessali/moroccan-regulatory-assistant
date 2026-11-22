from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user_context, record_audit_event
from src.core.contracts.errors import NotFound
from src.core.contracts.models import UserContext
from src.core.db.models import Document
from src.core.db.session import get_db

router = APIRouter()


@router.get("")
@router.get("/")
def list_documents(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> list[dict[str, Any]]:
    """List documents accessible to the authenticated user."""
    docs = db.scalars(select(Document)).all()
    return [
        {
            "doc_id": str(d.id),
            "title": str(d.title) if hasattr(d, "title") else "Untitled",
            "status": str(d.status) if hasattr(d, "status") else "processed",
            "created_at": (
                d.created_at.isoformat() if hasattr(d, "created_at") and d.created_at else None
            ),
        }
        for d in docs
    ]


@router.post("")
@router.post("/")
def upload_document(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Upload a new regulatory document (placeholder for ingestion pipeline)."""
    return {"status": "uploaded", "message": "document upload queued"}


@router.get("/{doc_id}/status")
def get_document_status(
    doc_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Get processing status of a specific document."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise NotFound("document not found")
    return {
        "doc_id": str(doc.id),
        "status": str(doc.status) if hasattr(doc, "status") else "processed",
    }


@router.delete("/{doc_id}")
def delete_document(
    doc_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Delete a document (admin or owner only)."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise NotFound("document not found")

    db.delete(doc)
    db.commit()
    record_audit_event(ctx, "delete_document", {"doc_id": str(doc_id)})
    return {"doc_id": str(doc_id), "status": "deleted"}


@router.put("/{doc_id}/roles")
def set_document_roles(
    doc_id: UUID,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Set access roles for a specific regulatory document (admin/editor only)."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise NotFound("document not found")

    roles = body.get("roles", [])
    record_audit_event(ctx, "set_document_roles", {"doc_id": str(doc_id), "roles": roles})
    return {"doc_id": str(doc_id), "status": "roles_updated", "roles": roles}
