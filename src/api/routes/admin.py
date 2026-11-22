from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import record_audit_event, require_admin
from src.core.contracts.enums import AccountRequestStatus
from src.core.contracts.errors import Conflict, InvalidInput, NotFound
from src.core.contracts.models import UserContext
from src.core.db.models import AccountRequest, Role, User
from src.core.db.session import get_db

router = APIRouter()


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Return all registered users (admin only)."""
    users = db.scalars(select(User)).all()
    return [
        {
            "user_id": str(u.id),
            "username": str(u.username),
            "full_name": str(u.full_name),
            "is_active": bool(u.is_active),
            "role": str(u.role.name) if u.role else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: UUID,
    body: dict[str, str],
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    """Update user role (admin only)."""
    user = db.get(User, user_id)
    if not user:
        raise NotFound("user not found")
    new_role_name = body.get("role")
    role = db.scalars(select(Role).where(Role.name == new_role_name)).first()
    if not role:
        raise NotFound("role not found")
    user.role_id = role.id
    db.commit()
    record_audit_event(
        ctx, "update_role", {"target_user_id": str(user_id), "new_role": new_role_name}
    )
    return {"status": "updated"}


@router.patch("/users/{user_id}/active")
def update_user_active(
    user_id: UUID,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    """Activate or deactivate user account instead of deletion."""
    user = db.get(User, user_id)
    if not user:
        raise NotFound("user not found")
    is_active = body.get("is_active")
    if is_active is None:
        raise InvalidInput("is_active field required")
    active_val = bool(is_active)
    user.is_active = active_val  # type: ignore[assignment]
    db.commit()
    record_audit_event(
        ctx, "update_active", {"target_user_id": str(user_id), "is_active": active_val}
    )
    return {"status": "updated"}


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List system roles."""
    roles = db.scalars(select(Role)).all()
    return [
        {
            "id": r.id,
            "name": str(r.name),
            "description": str(r.description),
            "web_enabled": bool(r.web_enabled),
        }
        for r in roles
    ]


@router.patch("/roles/{role_id}/web")
def update_role_web(
    role_id: int,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    """Update web search permission for a role."""
    role = db.get(Role, role_id)
    if not role:
        raise NotFound("role not found")
    web_enabled = body.get("web_enabled")
    if web_enabled is None:
        raise InvalidInput("web_enabled field required")
    role.web_enabled = bool(web_enabled)  # type: ignore[assignment]
    db.commit()
    return {"status": "updated"}


@router.get("/audit")
def get_audit_logs(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Return system audit logs."""
    from src.core.db.models import AuditLog

    logs = db.scalars(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(100)).all()
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


@router.get("/account-requests")
def list_account_requests(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List pending account requests."""
    reqs = db.scalars(select(AccountRequest)).all()
    return [
        {
            "request_id": str(r.id),
            "username": str(r.username),
            "full_name": str(r.full_name),
            "status": str(r.status),
            "created_at": r.created_at.isoformat()
            if hasattr(r, "created_at") and r.created_at
            else None,
        }
        for r in reqs
    ]


@router.post("/account-requests/{request_id}/approve")
def approve_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    """Approve an account request and create active user."""
    req = db.get(AccountRequest, request_id)
    if not req:
        raise NotFound("request not found")
    if req.status != AccountRequestStatus.PENDING.value:
        raise Conflict("request already processed")

    default_role = db.scalars(select(Role).where(Role.name == "user")).first()
    if not default_role:
        default_role = db.scalars(select(Role)).first()
    if not default_role:
        raise NotFound("default role not found")

    new_user = User(
        username=req.username,
        hashed_password=req.hashed_password,
        full_name=req.full_name,
        is_active=True,
        role_id=default_role.id,
    )
    db.add(new_user)
    req.status = AccountRequestStatus.APPROVED.value  # type: ignore[assignment]
    db.commit()
    record_audit_event(ctx, "approve_account_request", {"request_id": str(request_id)})
    return {"status": "approved"}


@router.post("/account-requests/{request_id}/reject")
def reject_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    """Reject an account request."""
    req = db.get(AccountRequest, request_id)
    if not req:
        raise NotFound("request not found")
    req.status = AccountRequestStatus.REJECTED.value  # type: ignore[assignment]
    db.commit()
    record_audit_event(ctx, "reject_request", {"request_id": str(request_id)})
    return {"status": "rejected"}
