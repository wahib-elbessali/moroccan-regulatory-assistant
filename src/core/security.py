"""Security module: Argon2 password hashing, HS256 JWT tokens, and user context (P5-14, P5-15)."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.contracts.enums import RoleName
from src.core.contracts.errors import Forbidden, Unauthenticated
from src.core.contracts.models import UserContext

_ph = PasswordHasher()
_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id (P5-14)."""
    return _ph.hash(password)


def get_password_hash(password: str) -> str:
    """Hache le mot de passe avec Argon2 (alias P5-14)."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie le hash Argon2 (P5-14)."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Crée un token JWT signé en HS256 (P5-15)."""
    secret_key = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("JWT_SECRET environment variable must be set.")

    to_encode = data.copy()
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
        expire = now + timedelta(minutes=expire_minutes)

    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(
        to_encode,
        secret_key,
        algorithm="HS256",
    )
    return str(encoded_jwt)


def get_current_usercontext(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> UserContext:
    """Extract and validate the JWT Bearer token into a UserContext (P5-15)."""
    if credentials is None or not credentials.credentials:
        raise Unauthenticated("Missing or invalid authorization header.")

    token = credentials.credentials
    secret_key = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("JWT_SECRET environment variable must be set.")

    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as err:
        raise Unauthenticated(f"Token validation failed: {err}") from err

    user_id_str = payload.get("sub") or payload.get("user_id")
    username = payload.get("username")
    role_str = payload.get("role")

    if not user_id_str or not username or not role_str:
        raise Unauthenticated("Token payload missing mandatory claims.")

    try:
        user_uuid = UUID(str(user_id_str))
        role = RoleName(str(role_str)).value
    except (ValueError, KeyError) as err:
        raise Forbidden("Invalid credentials or payload.") from err

    return UserContext(
        user_id=user_uuid,
        username=str(username),
        role=role,
        web_enabled=bool(payload.get("web_enabled", True)),
    )


get_current_user_context = get_current_usercontext

__all__ = [
    "hash_password",
    "get_password_hash",
    "verify_password",
    "create_access_token",
    "get_current_usercontext",
    "get_current_user_context",
]
