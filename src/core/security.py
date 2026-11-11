# src/core/security.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()

def get_password_hash(password: str) -> str:
    """Hache le mot de passe avec Argon2 (P5-14)."""
    return _ph.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie le hash Argon2 (P5-14)."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False