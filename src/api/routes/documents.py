from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user_context, record_audit_event
from src.core.contracts.enums import AuditAction, DocStatus, RoleName
from src.core.contracts.errors import Conflict, InvalidInput, NotFound
from src.core.contracts.models import DocumentMeta, DocumentResponse, UserContext
from src.core.contracts.registry import (
    get_document_rights,
    get_ingestion,
    get_retrieval,
)
from src.core.db.models import Document, DocumentRole, Role
from src.core.db.rights import list_visible_documents
from src.core.db.session import get_db
from src.core.security import validate_roles

router = APIRouter()

_IN_PROGRESS_STATUSES = {
    DocStatus.RECEIVED.value,
    DocStatus.EXTRACTING.value,
    DocStatus.CHUNKED.value,
}


def _can_access_document(doc: Document, ctx: UserContext) -> bool:
    if doc.owner_id is not None:
        return UUID(str(doc.owner_id)) == ctx.user_id
    if ctx.role == RoleName.ADMIN.value:
        return True
    doc_role_names = {dr.role.name for dr in doc.allowed_roles}
    return ctx.role in doc_role_names


def _can_delete_document(doc: Document, ctx: UserContext) -> bool:
    if doc.owner_id is not None:
        return UUID(str(doc.owner_id)) == ctx.user_id
    return ctx.role in (RoleName.ADMIN.value, RoleName.EDITEUR.value)


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


@router.post("", status_code=202)
@router.post("/", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,  # noqa: B008
    file: UploadFile = File(...),  # noqa: B008
    title: str | None = Form(default=None),  # noqa: B008
    source: str | None = Form(default=None),  # noqa: B008
    date: str | None = Form(default=None),  # noqa: B008
    roles: list[str] = Form(default=[]),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> dict[str, Any]:
    """Upload a document, schedule background ingestion, and return 202 (P5-24, P5-25)."""
    file_name = file.filename or ""
    if not file_name.strip():
        raise InvalidInput("missing filename")

    file_bytes = await file.read()
    clean_title = (title or Path(file_name).stem).strip()
    if not clean_title:
        raise InvalidInput("title cannot be empty")

    clean_roles = [r.strip() for r in roles if r and r.strip()]
    if ctx.role == RoleName.EDITEUR.value:
        if not clean_roles:
            raise InvalidInput("editeur must specify at least one role")
        owner_id: UUID | None = None
    else:
        owner_id = ctx.user_id
        clean_roles = []

    validated_roles = validate_roles(clean_roles, private=(owner_id is not None))

    meta = DocumentMeta(
        title=clean_title,
        source_file=file_name,
        source=source,
        date=date,
    )

    doc_id, stored_path = get_document_rights().create_document(
        file_bytes=file_bytes,
        file_name=file_name,
        meta=meta,
        owner_id=owner_id,
        uploaded_by=ctx.user_id,
    )

    if validated_roles:
        role_rows = list(db.scalars(select(Role).where(Role.name.in_(validated_roles))).all())
        if len(role_rows) != len(validated_roles):
            raise InvalidInput("unknown role in roles list")
        db.execute(delete(DocumentRole).where(DocumentRole.document_id == doc_id))
        for role_row in role_rows:
            db.add(DocumentRole(document_id=doc_id, role_id=role_row.id))
        db.commit()

    doc = db.scalars(select(Document).where(Document.id == doc_id)).one_or_none()
    if doc is None:
        raise NotFound("document not found")

    background_tasks.add_task(
        get_ingestion().ingest,
        doc_id,
        stored_path,
        meta,
        validated_roles,
        owner_id,
    )
    return {
        "doc_id": str(doc.id),
        "status": str(doc.status),
    }


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
        raise NotFound("document not found")

    status = str(doc.status) if doc.status else get_document_rights().get_status(doc_id)
    return {
        "doc_id": str(doc.id),
        "status": status,
        "error": str(doc.error) if doc.error is not None else None,
    }


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> Response:
    """Delete a document via P1 ingestion after hiding, then remove storage and DB row."""
    doc = db.scalars(select(Document).where(Document.id == doc_id)).one_or_none()
    if doc is None:
        raise NotFound("document not found")
    if not _can_delete_document(doc, ctx):
        raise NotFound("document not found")

    if str(doc.status) in _IN_PROGRESS_STATUSES:
        raise Conflict("document is being processed")

    get_retrieval().hide(doc_id)
    get_ingestion().delete(doc_id)

    for upload_candidate in Path("storage/uploads").glob(f"{doc_id}.*"):
        upload_candidate.unlink(missing_ok=True)

    db.execute(delete(DocumentRole).where(DocumentRole.document_id == doc_id))
    db.delete(doc)
    db.commit()

    record_audit_event(ctx, AuditAction.DOCUMENT_DELETE.value, {"doc_id": doc_id})
    return Response(status_code=204)

