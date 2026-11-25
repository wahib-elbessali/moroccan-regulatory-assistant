import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.api.deps import record_audit_event, require_admin
from src.core.config import cfg
from src.core.contracts.enums import AccountRequestStatus, RoleName
from src.core.contracts.errors import Conflict, InvalidInput, NotFound
from src.core.contracts.models import (
    AccountRequestResponse,
    RoleResponse,
    UserContext,
    UserCreate,
    UserResponse,
)
from src.core.contracts.registry import get_document_rights
from src.core.db.models import AccountRequest, AuditLog, Role, User
from src.core.db.rights import (
    approve_account_request,
    audit_actor_var,
    reject_account_request,
)
from src.core.db.session import get_db
from src.core.security import get_password_hash

router = APIRouter()

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


class UpdateUserRoleIn(BaseModel):
    role_id: int


class ApproveRequestIn(BaseModel):
    role_id: int


class SetDocumentRolesIn(BaseModel):
    roles: list[str]


def _count_active_admins(db: Session) -> int:
    admin_role = db.scalars(select(Role).where(Role.name == RoleName.ADMIN.value)).first()
    if admin_role is None:
        return 0
    count = db.scalar(
        select(func.count(User.id)).where(
            User.role_id == admin_role.id,
            User.is_active.is_(True),
        )
    )
    return int(count or 0)


def _to_user_response(user: User) -> UserResponse:
    created_at = user.created_at if isinstance(user.created_at, datetime) else datetime.now(UTC)
    return UserResponse(
        user_id=UUID(str(user.id)),
        username=str(user.username),
        full_name=str(user.full_name),
        role=str(user.role.name),
        is_active=bool(user.is_active),
        created_at=created_at,
    )


def _to_account_request_response(req: AccountRequest) -> AccountRequestResponse:
    created_at = req.created_at if isinstance(req.created_at, datetime) else datetime.now(UTC)
    decided_at = req.decided_at if isinstance(req.decided_at, datetime) else None
    return AccountRequestResponse(
        request_id=UUID(str(req.id)),
        username=str(req.username),
        full_name=str(req.full_name),
        status=str(req.status),
        created_at=created_at,
        decided_by=UUID(str(req.decided_by)) if req.decided_by is not None else None,
        decided_at=decided_at,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> list[UserResponse]:
    """Return all registered users (admin only)."""
    _ = ctx
    users = list(db.scalars(select(User)).all())
    return [_to_user_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> UserResponse:
    """Create a new user directly (admin only)."""
    username = body.username.strip()
    full_name = body.full_name.strip()
    min_pw_len = cfg.auth.min_password_length if cfg.auth else 8

    if not _USERNAME_RE.match(username):
        raise InvalidInput("Username must be 3-32 chars (letters, digits, '.', '_', '-').")
    if len(body.password) < min_pw_len:
        raise InvalidInput(f"Password must be at least {min_pw_len} characters long.")
    if not (1 <= len(full_name) <= 100):
        raise InvalidInput("Full name must be between 1 and 100 characters.")

    role = db.get(Role, body.role_id)
    if role is None:
        raise NotFound("role not found")

    if db.scalars(select(User).where(User.username == username)).first() is not None:
        raise Conflict("username already exists")

    user = User(
        username=username,
        hashed_password=get_password_hash(body.password),
        full_name=full_name,
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit_event(
        ctx,
        "create_user",
        {"created_user_id": str(user.id), "username": username, "role": str(role.name)},
    )
    return _to_user_response(user)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: UUID,
    body: UpdateUserRoleIn,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> UserResponse:
    """Update user role by role_id (admin only, P5-31e/f)."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("user not found")

    role = db.get(Role, body.role_id)
    if role is None:
        raise NotFound("role not found")

    if user.id == ctx.user_id and user.role_id != role.id:
        raise InvalidInput("admin cannot change their own role")

    was_active_admin = bool(user.is_active) and str(user.role.name) == RoleName.ADMIN.value
    will_be_admin = str(role.name) == RoleName.ADMIN.value
    if was_active_admin and not will_be_admin and _count_active_admins(db) <= 1:
        raise InvalidInput("cannot demote the last active admin")

    user.role_id = role.id
    db.commit()
    db.refresh(user)
    record_audit_event(
        ctx,
        "update_role",
        {"target_user_id": str(user_id), "new_role_id": role.id, "new_role": str(role.name)},
    )
    return _to_user_response(user)


@router.patch("/users/{user_id}/active", response_model=UserResponse)
def update_user_active(
    user_id: UUID,
    body: dict[str, Any],
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> UserResponse:
    """Activate or deactivate user account instead of deletion (P5-31e/f)."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    if "is_active" not in body or body["is_active"] is None:
        raise InvalidInput("is_active field required")

    active_value = bool(body["is_active"])
    if user.id == ctx.user_id and not active_value:
        raise InvalidInput("admin cannot deactivate their own account")

    was_active_admin = bool(user.is_active) and str(user.role.name) == RoleName.ADMIN.value
    if was_active_admin and not active_value and _count_active_admins(db) <= 1:
        raise InvalidInput("cannot deactivate the last active admin")

    user.is_active = active_value  # type: ignore[assignment]
    db.commit()
    db.refresh(user)
    record_audit_event(
        ctx,
        "update_active",
        {"target_user_id": str(user_id), "is_active": active_value},
    )
    return _to_user_response(user)


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> list[RoleResponse]:
    """List system roles."""
    _ = ctx
    roles = list(db.scalars(select(Role)).all())
    return [
        RoleResponse(
            role_id=int(r.id),
            name=str(r.name),
            web_enabled=bool(r.web_enabled),
        )
        for r in roles
    ]


@router.patch("/roles/{role_id}/web", response_model=RoleResponse)
def update_role_web(
    role_id: int,
    body: dict[str, Any],
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> RoleResponse:
    """Update web search permission for a role."""
    _ = ctx
    role = db.get(Role, role_id)
    if role is None:
        raise NotFound("role not found")
    if "web_enabled" not in body or body["web_enabled"] is None:
        raise InvalidInput("web_enabled field required")

    db.execute(update(Role).where(Role.id == role_id).values(web_enabled=bool(body["web_enabled"])))
    db.commit()
    db.refresh(role)
    return RoleResponse(
        role_id=int(role.id),
        name=str(role.name),
        web_enabled=bool(role.web_enabled),
    )


@router.put("/documents/{doc_id}/roles")
def set_document_roles_admin(
    doc_id: str,
    body: SetDocumentRolesIn,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    """Set access roles for a document atomically (admin only, P5-26b, P5-31)."""
    token = audit_actor_var.set(ctx.user_id)
    try:
        return get_document_rights().set_document_roles(doc_id, body.roles)
    finally:
        audit_actor_var.reset(token)


@router.get("/audit")
def get_audit_logs(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> list[dict[str, Any]]:
    """Return system audit logs."""
    _ = ctx
    logs = list(db.scalars(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(100)).all())
    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "action": str(log.action),
            "details": log.details,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


@router.get("/account-requests", response_model=list[AccountRequestResponse])
def list_account_requests(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> list[AccountRequestResponse]:
    """List account requests."""
    _ = ctx
    reqs = list(db.scalars(select(AccountRequest)).all())
    return [_to_account_request_response(r) for r in reqs]


@router.post("/account-requests/{request_id}/approve", response_model=AccountRequestResponse)
def approve_request(
    request_id: UUID,
    body: ApproveRequestIn,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> AccountRequestResponse:
    """Approve a pending account request with an explicit role_id (P5-41)."""
    req = db.get(AccountRequest, request_id)
    if req is None:
        raise NotFound("request not found")
    if req.status != AccountRequestStatus.PENDING.value:
        raise Conflict("request already processed")

    role = db.get(Role, body.role_id)
    if role is None:
        raise NotFound("role not found")

    approve_account_request(
        session=db,
        request_id=request_id,
        role_name=str(role.name),
        decided_by=ctx.user_id,
    )
    updated_req = db.get(AccountRequest, request_id)
    if updated_req is None:
        raise NotFound("request not found")
    return _to_account_request_response(updated_req)


@router.post("/account-requests/{request_id}/reject", response_model=AccountRequestResponse)
def reject_request(
    request_id: UUID,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> AccountRequestResponse:
    """Reject a pending account request (P5-41, P5-42)."""
    req = db.get(AccountRequest, request_id)
    if req is None:
        raise NotFound("request not found")
    if req.status != AccountRequestStatus.PENDING.value:
        raise Conflict("request already processed")

    updated = reject_account_request(
        session=db,
        request_id=request_id,
        decided_by=ctx.user_id,
    )
    return _to_account_request_response(updated)
