"""Path configuration and shared fixtures for tests (P5-08)."""

import sys
from pathlib import Path
from uuid import UUID

import pytest

from src.core.contracts.enums import RoleName
from src.core.contracts.models import UserContext

# Ensure repository root is on sys.path so 'tests.ingestion.doubles' can be imported cleanly
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# UUIDs fixes obligatoires pour P5-08 et interopérabilité P1
LECTEUR_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_LECTEUR_ID = UUID("44444444-4444-4444-4444-444444444444")
EDITEUR_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def lecteur_ctx() -> UserContext:
    """Fixture lecteur pour les tests de requêtes et de chunks privés."""
    return UserContext(
        user_id=LECTEUR_ID,
        username="lecteur_test",
        role=RoleName.LECTEUR.value,
        web_enabled=True,
        request_id=None,
    )


@pytest.fixture
def other_lecteur_ctx() -> UserContext:
    """Fixture second lecteur pour tester l'isolation stricte des documents."""
    return UserContext(
        user_id=OTHER_LECTEUR_ID,
        username="other_lecteur_test",
        role=RoleName.LECTEUR.value,
        web_enabled=True,
        request_id=None,
    )


@pytest.fixture
def editeur_ctx() -> UserContext:
    """Fixture éditeur de corpus juridique."""
    return UserContext(
        user_id=EDITEUR_ID,
        username="editeur_test",
        role=RoleName.EDITEUR.value,
        web_enabled=True,
        request_id=None,
    )


@pytest.fixture
def admin_ctx() -> UserContext:
    """Fixture administrateur système."""
    return UserContext(
        user_id=ADMIN_ID,
        username="admin_test",
        role=RoleName.ADMIN.value,
        web_enabled=True,
        request_id=None,
    )
