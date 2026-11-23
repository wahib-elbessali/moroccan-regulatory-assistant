"""Real PostgreSQL-backed DocumentRights service (00-shared Â§6.1, P5-24 to P5-28b)."""

from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.config import cfg
from src.core.contracts.enums import (
    ALLOWED_TRANSITIONS,
    AccountRequestStatus,
    AuditAction,
    DocStatus,
)
from src.core.contracts.errors import Conflict, InvalidInput, NotFound
from src.core.contracts.ids import make_doc_id, make_file_hash
from src.core.contracts.models import DocumentMeta, UserContext, is_public
from src.core.contracts.registry import get_audit, get_leak_index, get_retrieval
from src.core.db.models import AccountRequest, Document, DocumentRole, Role, User
from src.core.db.session import SessionLocal
from src.core.security import validate_roles

ALLOWED_SUFFIXES: set[str] = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"}

# Optional actor ID set by HTTP routes before calling set_document_roles (None for background ingestion)
audit_actor_var: ContextVar[UUID | None] = ContextVar("audit_actor", default=None)


class RealDocumentRights:
    """PostgreSQL implementation of DocumentRights protocol."""

    def create_document(
        self,
        file_bytes: bytes,
        file_name: str,
        meta: DocumentMeta,
        owner_id: UUID | None,
        uploaded_by: UUID | None,
    ) -> tuple[str, Path]:
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_SUFFIXES:
            raise InvalidInput("unsupported format")

        if len(file_bytes) > cfg.uploads.max_bytes:
            raise InvalidInput("file too large")

        doc_id = make_doc_id(file_bytes, owner_id)
        upload_dir = Path("storage/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = upload_dir / f"{doc_id}{ext}"

        source_clean = meta.source.strip()[:500] if meta.source else None
        date_clean = meta.date.strip()[:500] if meta.date else None

        with SessionLocal() as session:
            if session.get(Document, doc_id) is not None:
                raise Conflict("already uploaded")

            stored_path.write_bytes(file_bytes)
            try:
                doc = Document(
                    id=doc_id,
                    title=meta.title.strip(),
                    source_file=file_name,
                    source=source_clean,
                    date=date_clean,
                    owner_id=owner_id,
                    status=DocStatus.RECEIVED.value,
                    file_hash=make_file_hash(file_bytes),
                    created_at=datetime.now(UTC),
                )
                session.add(doc)
                session.commit()
            except Exception:
                stored_path.unlink(missing_ok=True)
                raise

        get_audit().log_action(
            uploaded_by,
            AuditAction.DOCUMENT_UPLOAD.value,
            {"doc_id": doc_id},
        )
        return doc_id, stored_path

    def get_status(self, doc_id: str) -> str:
        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                raise NotFound("document not found")
            return str(doc.status)

    def set_status(self, doc_id: str, status: str, error: str | None = None) -> None:
        try:
            target_status = DocStatus(status)
        except ValueError as err:
            raise InvalidInput(f"unknown status: {status}") from err

        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                raise NotFound("document not found")

            current_status = DocStatus(str(doc.status))
            if target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
                raise InvalidInput(
                    f"invalid status transition: {current_status.value} -> {target_status.value}"
                )

            doc.status = target_status.value  # type: ignore[assignment]
            doc.error = error[:500] if error else None  # type: ignore[assignment]
            session.commit()

    def set_content_hash(self, doc_id: str, content_hash: str) -> None:
        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                raise NotFound("document not found")
            doc.content_hash = content_hash  # type: ignore[assignment]
            session.commit()

    def set_document_roles(self, doc_id: str, roles: list[str]) -> dict[str, Any]:
        """Validate roles, update DB + retrieval + leak index atomically, and publish (P5-26 to P5-28b)."""
        with SessionLocal() as session:
            doc = session.get(Document, doc_id)
            if doc is None:
                raise NotFound("document not found")
            is_private = doc.owner_id is not None
            current_status = DocStatus(str(doc.status))

            validated_roles = validate_roles(roles, private=is_private)

            if current_status not in (DocStatus.INDEXED, DocStatus.READY):
                raise InvalidInput("document is not indexed")

            role_rows: list[Role] = []
            if validated_roles:
                role_rows = list(
                    session.scalars(select(Role).where(Role.name.in_(validated_roles))).all()
                )
                if len(role_rows) != len(validated_roles):
                    raise InvalidInput("unknown role in roles list")

        retrieval = get_retrieval()
        leak = get_leak_index()
        actor_id = audit_actor_var.get()

        if current_status == DocStatus.READY:
            self.set_status(doc_id, DocStatus.INDEXED.value)

        try:
            retrieval.hide(doc_id)

            with SessionLocal() as session:
                session.execute(delete(DocumentRole).where(DocumentRole.document_id == doc_id))
                for role_row in role_rows:
                    session.add(DocumentRole(document_id=doc_id, role_id=role_row.id))
                session.commit()

            retrieval.update_roles(doc_id, validated_roles)
            leak.set_blocking(doc_id, blocking=not is_public(validated_roles))
            retrieval.show(doc_id)
            self.set_status(doc_id, DocStatus.READY.value)

            get_audit().log_action(
                actor_id,
                AuditAction.ADMIN_UPDATE.value,
                {"doc_id": doc_id, "roles": validated_roles},
            )
            return {"doc_id": doc_id, "status": DocStatus.READY.value}

        except Exception as exc:
            try:
                retrieval.hide(doc_id)
            except Exception:
                pass
            if self.get_status(doc_id) != DocStatus.FAILED.value:
                self.set_status(doc_id, DocStatus.FAILED.value, error=str(exc)[:500])
            get_audit().log_action(
                actor_id,
                AuditAction.ADMIN_UPDATE.value,
                {"doc_id": doc_id, "failed": str(exc)[:200]},
            )
            raise


def real_document_rights() -> RealDocumentRights:
    """Factory used by registry.py when contracts.document_rights == 'real'."""
    return RealDocumentRights()


def list_visible_documents(session: Session, ctx: UserContext) -> list[Document]:
    """Return documents visible to ctx (admin sees all corpus docs, others see allowed roles + own private)."""
    stmt = select(Document).order_by(Document.created_at.desc())
    docs = list(session.scalars(stmt).all())
    visible: list[Document] = []
    for doc in docs:
        if doc.owner_id is not None:
            if UUID(str(doc.owner_id)) == ctx.user_id:
                visible.append(doc)
        elif ctx.role == "admin":
            visible.append(doc)
        else:
            doc_role_names = {dr.role.name for dr in doc.allowed_roles}
            if ctx.role in doc_role_names:
                visible.append(doc)
    return visible


def approve_account_request(
    session: Session,
    request_id: UUID,
    role_name: str,
    decided_by: UUID,
) -> User:
    """Approve a pending AccountRequest, create the User account, and record audit (P5-41)."""
    req = session.get(AccountRequest, request_id)
    if req is None:
        raise NotFound("account request not found")
    if req.status != AccountRequestStatus.PENDING.value:
        raise InvalidInput("account request already decided")

    role_obj = session.scalars(select(Role).where(Role.name == role_name)).one_or_none()
    if role_obj is None:
        raise InvalidInput(f"unknown role: {role_name}")

    if session.scalars(select(User).where(User.username == req.username)).first() is not None:
        raise Conflict("username already exists")

    user = User(
        username=req.username,
        hashed_password=req.hashed_password,
        full_name=req.full_name,
        role_id=role_obj.id,
        is_active=True,
    )
    session.add(user)
    req.status = AccountRequestStatus.APPROVED.value  # type: ignore[assignment]
    req.decided_by = decided_by  # type: ignore[assignment]
    req.decided_at = datetime.now(UTC)  # type: ignore[assignment]
    session.commit()
    session.refresh(user)

    get_audit().log_action(
        decided_by,
        AuditAction.ADMIN_UPDATE.value,
        {"account_request_id": str(request_id), "approved_user": str(user.id), "role": role_name},
    )
    return user


def reject_account_request(
    session: Session,
    request_id: UUID,
    decided_by: UUID,
) -> AccountRequest:
    """Reject a pending AccountRequest and record audit (P5-42)."""
    req = session.get(AccountRequest, request_id)
    if req is None:
        raise NotFound("account request not found")
    if req.status != AccountRequestStatus.PENDING.value:
        raise InvalidInput("account request already decided")

    req.status = AccountRequestStatus.REJECTED.value  # type: ignore[assignment]
    req.decided_by = decided_by  # type: ignore[assignment]
    req.decided_at = datetime.now(UTC)  # type: ignore[assignment]
    session.commit()
    session.refresh(req)

    get_audit().log_action(
        decided_by,
        AuditAction.ADMIN_UPDATE.value,
        {"account_request_id": str(request_id), "rejected": True},
    )
    return req
