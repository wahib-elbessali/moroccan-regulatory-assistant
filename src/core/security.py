"""Security module: Argon2 password hashing, HS256 JWT tokens, and user context (P5-14, P5-15, P5-19)."""

import os
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.core.config import cfg
from src.core.contracts.errors import Unauthenticated
from src.core.contracts.models import UserContext
from src.core.db.models import User
from src.core.db.session import get_db

_ph = PasswordHasher()
_bearer_scheme = HTTPBearer(auto_error=False)

request_id_var: ContextVar[UUID | None] = ContextVar("request_id", default=None)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id (P5-14)."""
    return _ph.hash(password)


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2id (alias P5-14)."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify an Argon2 password hash (P5-14)."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a minimal HS256 JWT access token holding only `sub` and `exp` (P5-15)."""
    secret_key = os.getenv("JWT_SECRET") or cfg.JWT_SECRET
    if not secret_key:
        raise RuntimeError("JWT_SECRET environment variable must be set.")

    sub = data.get("sub") or data.get("user_id")
    if not sub:
        raise ValueError("Token payload must include 'sub'.")

    now = datetime.now(UTC)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        token_minutes = cfg.auth.token_minutes if cfg.auth else 60
        expire = now + timedelta(minutes=token_minutes)

    payload = {
        "sub": str(sub),
        "exp": expire,
    }
    return str(jwt.encode(payload, secret_key, algorithm="HS256"))


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an HS256 JWT access token."""
    secret_key = os.getenv("JWT_SECRET") or cfg.JWT_SECRET
    if not secret_key:
        raise RuntimeError("JWT_SECRET environment variable must be set.")
    return dict(jwt.decode(token, secret_key, algorithms=["HS256"]))


def get_current_user_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserContext:
    """Decode token and re-read user, role, web_enabled, and active status from DB (P5-19, P5-23)."""
    if credentials is None or not credentials.credentials:
        raise Unauthenticated("invalid token")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as err:
        raise Unauthenticated("invalid token") from err

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("invalid token")

    req_id = request_id_var.get() or uuid4()

    return UserContext(
        user_id=UUID(str(user.id)),
        username=str(user.username),
        role=str(user.role.name),
        web_enabled=bool(user.role.web_enabled),
        request_id=req_id,
    )


get_current_usercontext = get_current_user_context

__all__ = [
    "request_id_var",
    "hash_password",
    "get_password_hash",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "get_current_user_context",
    "get_current_usercontext",
]
