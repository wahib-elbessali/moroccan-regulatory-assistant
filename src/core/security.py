"""Security module: Argon2 password hashing and HS256 JWT tokens (P5-14, P5-15)."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


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
