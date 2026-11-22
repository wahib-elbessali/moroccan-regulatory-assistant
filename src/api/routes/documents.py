from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user_context, record_audit_event
from src.core.contracts.enums import DocStatus, RoleName
from src.core.contracts.errors import Forbidden, InvalidInput, NotFound
from src.core.contracts.models import DocumentMeta, DocumentResponse, UserContext
from src.core.contracts.registry import get_document_rights, get_leak_index, get_retrieval
from src.core.db.models import Document
from src.core.db.rights import list_visible_documents
from src.core.db.session import get_db

router = APIRouter()


def _can_access_document(doc: Document, ctx: UserContext) -> bool:
    if doc.owner_id is not None:
        return UUID(str(doc.owner_id)) == ctx.user_id
    if ctx.role == RoleName.ADMIN.value:
        return True
    doc_role_names = {dr.role.name for dr in doc.allowed_roles}
    return ctx.role in doc_role_names


def _can_delete_document(doc: Document, ctx: UserContext) -> bool:
    if ctx.role == RoleName.ADMIN.value:
        return True
    return doc.owner_id is not None and UUID(str(doc.owner_id)) == ctx.user_id


def _to_document_response(doc: Document, ctx: UserContext) -> DocumentResponse:
    is_private = doc.owner_id is not None
    is_mine = is_private and UUID(str(doc.owner_id)) == ctx.user_id
    roles = [] if is_private else sorted({str(dr.role.name) for dr in doc.allowed_roles})
    created_at = doc.created_at if isinstance(doc.created_at, datetime) else datetime.now(UTC)
    return DocumentResponse(
        doc_id=str(doc.id),
        title=str(doc.title),
        source_file=str(doc.source_file),
        source=str(doc.source) if doc.source is not None else None,
        date=str(doc.date) if doc.date is not None else None,
        status=str(doc.status),
        error=str(doc.error) if doc.error is not None else None,
        roles=roles,
        is_mine=is_mine,
        created_at=created_at,
    )


@router.get("", response_model=list[DocumentResponse])
@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> list[DocumentResponse]:
    """List documents visible to the authenticated user (P5-29c)."""
    docs = list_visible_documents(db, ctx)
    return [_to_document_response(doc, ctx) for doc in docs]


@router.post("", response_model=DocumentResponse, status_code=201)
@router.post("/", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),  # noqa: B008
    title: str | None = Form(default=None),  # noqa: B008
    source: str | None = Form(default=None),  # noqa: B008
    date: str | None = Form(default=None),  # noqa: B008
    private: bool = Form(default=False),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> DocumentResponse:
    """Upload a document and persist its metadata row (P5-24, P5-25)."""
    file_name = file.filename or ""
    if not file_name.strip():
        raise InvalidInput("missing filename")

    file_bytes = await file.read()
    clean_title = (title or Path(file_name).stem).strip()
    if not clean_title:
        raise InvalidInput("title cannot be empty")

    if private:
        owner_id: UUID | None = ctx.user_id
    else:
        if ctx.role not in (RoleName.ADMIN.value, RoleName.EDITEUR.value):
            raise Forbidden("only admin or editeur can upload corpus documents")
        owner_id = None

    meta = DocumentMeta(
        title=clean_title,
        source_file=file_name,
        source=source,
        date=date,
    )

    doc_id, _stored_path = get_document_rights().create_document(
        file_bytes=file_bytes,
        file_name=file_name,
        meta=meta,
        owner_id=owner_id,
        uploaded_by=ctx.user_id,
    )

    doc = db.scalars(select(Document).where(Document.id == doc_id)).one_or_none()
    if doc is None:
        raise NotFound("document not found")
    return _to_document_response(doc, ctx)


@router.get("/{doc_id}/status")
def get_document_status(
    doc_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> dict[str, Any]:
    """Get processing status of a specific document (P5-29)."""
    doc = db.scalars(select(Document).where(Document.id == doc_id)).one_or_none()
    if doc is None:
        raise NotFound("document not found")
    if not _can_access_document(doc, ctx):
        raise Forbidden("forbidden")

    status = str(doc.status) if doc.status else get_document_rights().get_status(doc_id)
    return {
        "doc_id": str(doc.id),
        "status": status,
        "error": str(doc.error) if doc.error is not None else None,
    }


@router.delete("/{doc_id}")
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> dict[str, Any]:
    """Delete a document from DB, retrieval index, and leak index (P5-29)."""
    doc = db.scalars(select(Document).where(Document.id == doc_id)).one_or_none()
    if doc is None:
        raise NotFound("document not found")
    if not _can_delete_document(doc, ctx):
        raise Forbidden("forbidden")

    try:
        get_retrieval().delete(doc_id)
    except Exception:
        pass

    try:
        get_leak_index().delete(doc_id)
    except Exception:
        pass

    for upload_candidate in Path("storage/uploads").glob(f"{doc_id}.*"):
        upload_candidate.unlink(missing_ok=True)

    db.delete(doc)
    db.commit()
    record_audit_event(ctx, "delete_document", {"doc_id": doc_id})
    return {
        "doc_id": doc_id,
        "status": DocStatus.DELETED.value if hasattr(DocStatus, "DELETED") else "deleted",
    }
