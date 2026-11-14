"""Fixtures communes (00-shared §9, P5-08).

Les secrets n'ont plus de valeur par défaut dans config.py : on les fixe ICI, avant tout import de
`src.core.config`, avec des valeurs de test. `setdefault` laisse passer un vrai .env/CI si présent.
"""

import os

os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")
os.environ.setdefault("JWT_SECRET", "x" * 32)
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
from pathlib import Path  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

import pytest  # noqa: E402

from src.core.contracts import Chunk, registry  # noqa: E402
from src.core.contracts.enums import RoleName  # noqa: E402
from src.core.contracts.models import UserContext  # noqa: E402

LECTEUR_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_LECTEUR_ID = UUID("44444444-4444-4444-4444-444444444444")
EDITEUR_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")

SAMPLE_CHUNKS_FILE = Path(__file__).parent / "fixtures" / "sample_chunks.jsonl"


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Chaque test part d'un registre vide et ne laisse aucun override derrière lui."""
    registry.reset()
    yield
    registry.reset()


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Charge tests/fixtures/sample_chunks.jsonl (P1-05), liste neuve à chaque test."""
    chunks: list[Chunk] = []
    with open(SAMPLE_CHUNKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks


def _ctx(user_id: UUID, username: str, role: RoleName, web_enabled: bool = True) -> UserContext:
    return UserContext(
        user_id=user_id,
        username=username,
        role=role.value,
        web_enabled=web_enabled,
        request_id=uuid4(),
    )


@pytest.fixture
def lecteur_ctx() -> UserContext:
    return _ctx(LECTEUR_ID, "lecteur_test", RoleName.LECTEUR)


@pytest.fixture
def other_lecteur_ctx() -> UserContext:
    """Second lecteur : sert aux tests d'isolation (T6, T15)."""
    return _ctx(OTHER_LECTEUR_ID, "other_lecteur_test", RoleName.LECTEUR)


@pytest.fixture
def editeur_ctx() -> UserContext:
    return _ctx(EDITEUR_ID, "editeur_test", RoleName.EDITEUR)


@pytest.fixture
def admin_ctx() -> UserContext:
    return _ctx(ADMIN_ID, "admin_test", RoleName.ADMIN)


@pytest.fixture
def fake_audit():
    """FakeAudit installé dans le registre : `audited_stream` y écrit, le test relit `.queries`."""
    from src.core.contracts.fakes.audit import FakeAudit

    audit = FakeAudit()
    registry.override("audit", audit)
    return audit


@pytest.fixture
def fake_rights():
    """FakeDocumentRights installé dans le registre."""
    from src.core.contracts.fakes.rights import FakeDocumentRights

    rights = FakeDocumentRights()
    registry.override("document_rights", rights)
    return rights
