import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import cfg
from src.core.contracts.enums import AccountRequestStatus, AuditAction
from src.core.contracts.errors import Conflict, InvalidInput, TooManyRequests, Unauthenticated
from src.core.contracts.models import AccountRequestIn, MeResponse, UserContext
from src.core.contracts.registry import get_audit
from src.core.db.models import AccountRequest, Role, User
from src.core.db.session import get_db
from src.core.security import (
    create_access_token,
    get_current_user_context,
    get_password_hash,
    verify_password,
)

router = APIRouter()

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
_DUMMY_HASH: str | None = None
_failed_attempts: dict[str, list[float]] = defaultdict(list)


def _get_dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = get_password_hash(str(uuid4()))
    return _DUMMY_HASH


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _is_locked_out(username: str) -> bool:
    auth_cfg = cfg.auth
    max_attempts = auth_cfg.max_failed_logins if auth_cfg else 5
    window_s = (auth_cfg.lockout_minutes if auth_cfg else 15) * 60
    now = time.monotonic()

    recent = [ts for ts in _failed_attempts[username] if now - ts < window_s]
    _failed_attempts[username] = recent
    return len(recent) >= max_attempts


def _record_failed_attempt(username: str) -> None:
    _failed_attempts[username].append(time.monotonic())


def _clear_failed_attempts(username: str) -> None:
    _failed_attempts.pop(username, None)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:  # noqa: B008
    """Authenticate user with constant-time Argon2 verification and audit logging (P5-16, P5-17, P5-18)."""
    username = body.username.strip()

    if _is_locked_out(username):
        verify_password(body.password, _get_dummy_hash())
        get_audit().log_action(None, AuditAction.LOGIN.value, {"success": False})
        raise Unauthenticated("wrong username or password")

    stmt = select(User).where(User.username == username)
    user = db.scalars(stmt).one_or_none()

    hashed = str(user.hashed_password) if user is not None else _get_dummy_hash()
    password_ok = verify_password(body.password, hashed)
    ok = user is not None and bool(user.is_active) and password_ok

    user_uuid = UUID(str(user.id)) if user is not None else None
    get_audit().log_action(user_uuid, AuditAction.LOGIN.value, {"success": ok})

    if not ok:
        _record_failed_attempt(username)
        raise Unauthenticated("wrong username or password")

    _clear_failed_attempts(username)
    token = create_access_token({"sub": str(user_uuid)})
    return TokenOut(access_token=token, token_type="bearer")


@router.get("/me", response_model=MeResponse)
def get_me(
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> MeResponse:
    """Return current user info and dynamically computed web_available flag (P5-16b)."""
    user = db.get(User, ctx.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("invalid token")

    role_obj: Role = user.role
    web_available = bool(cfg.web.enabled) and bool(role_obj.web_enabled)
    return MeResponse(
        user_id=UUID(str(user.id)),
        username=str(user.username),
        role=str(role_obj.name),
        web_available=web_available,
    )


@router.post("/account-requests", status_code=202)
def create_account_request(
    body: AccountRequestIn,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Submit a new account registration request without authentication (P5-38 to P5-40)."""
    username = body.username.strip()
    full_name = body.full_name.strip()
    min_pw_len = cfg.auth.min_password_length if cfg.auth else 8
    max_pending = cfg.auth.max_pending_requests if cfg.auth else 50

    if not _USERNAME_RE.match(username):
        raise InvalidInput("Username must be 3-32 chars (letters, digits, '.', '_', '-').")
    if len(body.password) < min_pw_len:
        raise InvalidInput(f"Password must be at least {min_pw_len} characters long.")
    if not (1 <= len(full_name) <= 100):
        raise InvalidInput("Full name must be between 1 and 100 characters.")

    pending_count = (
        db.scalar(
            select(func.count())
            .select_from(AccountRequest)
            .where(AccountRequest.status == AccountRequestStatus.PENDING.value)
        )
        or 0
    )
    if pending_count >= max_pending:
        raise TooManyRequests("too many pending requests, try later")

    user_exists = db.scalars(select(User).where(User.username == username)).first() is not None
    pending_exists = (
        db.scalars(
            select(AccountRequest).where(
                AccountRequest.username == username,
                AccountRequest.status == AccountRequestStatus.PENDING.value,
            )
        ).first()
        is not None
    )
    if user_exists or pending_exists:
        raise Conflict("username not available")

    req_id = uuid4()
    req = AccountRequest(
        id=req_id,
        username=username,
        hashed_password=get_password_hash(body.password),
        full_name=full_name,
        status=AccountRequestStatus.PENDING.value,
        created_at=datetime.now(UTC),
    )
    db.add(req)
    db.commit()

    return {"request_id": str(req_id), "status": AccountRequestStatus.PENDING.value}
