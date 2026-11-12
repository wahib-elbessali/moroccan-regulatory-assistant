"""Shared test fixtures (00-shared §9).

Note: The UserContext fixtures for P5 (lecteur_ctx, editeur_ctx, admin_ctx, other_lecteur_ctx,
specified in P5-08) will be added to this root conftest.py once P5 lands.
"""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.core.contracts import Chunk
from src.core.contracts.enums import RoleName
from src.core.contracts.models import UserContext

LECTEUR_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_LECTEUR_ID = UUID("44444444-4444-4444-4444-444444444444")
EDITEUR_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")

SAMPLE_CHUNKS_FILE = Path(__file__).parent / "fixtures" / "sample_chunks.jsonl"


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Loads all chunks from tests/fixtures/sample_chunks.jsonl (P1-05).

    Returns a freshly validated and constructed list on each test call (function scope)
    so modifications made by one test do not affect others.
    """
    chunks: list[Chunk] = []
    with open(SAMPLE_CHUNKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks


@pytest.fixture
def lecteur_ctx() -> UserContext:
    """Fixture lecteur pour les tests."""
    return UserContext(
        user_id=LECTEUR_ID,
        username="lecteur_test",
        role=RoleName.LECTEUR.value,
        web_enabled=True,
        request_id=uuid4(),
    )


@pytest.fixture
def other_lecteur_ctx() -> UserContext:
    """Fixture second lecteur pour tester l'isolation."""
    return UserContext(
        user_id=OTHER_LECTEUR_ID,
        username="other_lecteur_test",
        role=RoleName.LECTEUR.value,
        web_enabled=True,
        request_id=uuid4(),
    )


@pytest.fixture
def editeur_ctx() -> UserContext:
    """Fixture éditeur de corpus juridique."""
    return UserContext(
        user_id=EDITEUR_ID,
        username="editeur_test",
        role=RoleName.EDITEUR.value,
        web_enabled=True,
        request_id=uuid4(),
    )


@pytest.fixture
def admin_ctx() -> UserContext:
    """Fixture administrateur système."""
    return UserContext(
        user_id=ADMIN_ID,
        username="admin_test",
        role=RoleName.ADMIN.value,
        web_enabled=True,
        request_id=uuid4(),
    )
