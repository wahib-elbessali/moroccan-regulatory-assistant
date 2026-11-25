"""Acceptance tests for P5-47 (conversation answer visibility) and P5-31e/f (admin safety)."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.core.db.rights as rights_mod
import src.core.db.session as session_mod
from src.api.deps import require_admin
from src.api.main import app
from src.core.contracts.enums import DocStatus
from src.core.contracts.models import Answer, Citation, UserContext
from src.core.db.base import Base
from src.core.db.models import Conversation, Document, DocumentRole, Role, User
from src.core.db.rights import RealDocumentRights
from src.core.db.session import get_db
from src.core.security import create_access_token, get_password_hash


@pytest.fixture()
def access_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, Session], None, None]:
    """Provide an isolated SQLite DB and TestClient for P5-47 and P5-31e/f tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(session_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(rights_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("src.api.main.init_db", lambda: None)

    session = TestingSessionLocal()

    admin_role = Role(id=1, name="admin", web_enabled=True)
    editeur_role = Role(id=2, name="editeur", web_enabled=True)
    lecteur_role = Role(id=3, name="lecteur", web_enabled=False)
    session.add_all([admin_role, editeur_role, lecteur_role])
    session.flush()

    admin_user = User(
        id=uuid4(),
        username="admin.user",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin User",
        role_id=admin_role.id,
        is_active=True,
    )
    active_user = User(
        id=uuid4(),
        username="alice.dev",
        hashed_password=get_password_hash("StrongPass123!"),
        full_name="Alice Developer",
        role_id=lecteur_role.id,
        is_active=True,
    )
    session.add_all([admin_user, active_user])
    session.commit()

    def _override_get_db() -> Generator[Session, None, None]:
        yield session

    def _override_require_admin() -> UserContext:
        return UserContext(
            user_id=UUID(str(admin_user.id)),
            username="admin.user",
            role="admin",
            web_enabled=True,
            request_id=uuid4(),
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = _override_require_admin

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, session

    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


def _make_citation(
    *,
    doc_id: str | None,
    title: str,
    url: str | None = None,
    page: int | None = 1,
    article: str = "المادة 1",
    source: str = "الجريدة الرسمية",
    date: str = "2026-01-01",
    excerpt: str = "مقتطف نصي",
) -> dict[str, Any]:
    return Citation(
        doc_id=doc_id,
        title=title,
        url=url,
        article=article,
        page=page,
        source=source,
        date=date,
        excerpt=excerpt,
    ).model_dump(mode="json")


def _create_user(
    db: Session,
    username: str,
    role: Role,
    is_active: bool = True,
) -> User:
    user = User(
        id=uuid4(),
        username=username,
        hashed_password=get_password_hash("StrongPass123!"),
        full_name=f"User {username}",
        role_id=role.id,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_document(
    db: Session,
    doc_id: str,
    status: str = DocStatus.READY.value,
) -> Document:
    doc = Document(
        id=doc_id,
        title=f"Doc {doc_id[:8]}",
        source_file=f"{doc_id[:8]}.pdf",
        owner_id=None,
        status=status,
        file_hash="0" * 64,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _create_conversation_with_citations(
    client: TestClient,
    db: Session,
    user: User,
    citations: list[dict[str, Any]],
    question: str = "ما هو نص الفصل؟",
) -> str:
    headers = _auth_headers(user)
    create_res = client.post("/conversations", json={}, headers=headers)
    assert create_res.status_code == 201
    conv_id: str = create_res.json()["conversation_id"]

    answer_payload = Answer(
        status="answered",
        text="نص إجابة اختبارية [1].",
        citations=[],
        confidence=0.9,
        language="ar",
    ).model_dump(mode="json")

    msg_res = client.post(
        f"/conversations/{conv_id}/messages",
        json={"question": question, "answer": answer_payload},
        headers=headers,
    )
    assert msg_res.status_code == 201

    conv = db.scalars(select(Conversation).where(Conversation.id == UUID(conv_id))).one()
    msg = conv.messages[0]
    updated_answer = dict(msg.answer or {})
    updated_answer["citations"] = citations
    msg.answer = updated_answer
    db.commit()
    return conv_id


# ---------------------------------------------------------------------------
# P5-47: GET /conversations/{id} availability & answer masking
# ---------------------------------------------------------------------------


def test_get_conversation_deleted_cited_doc_returns_unavailable(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    user = db_session.scalars(select(User).where(User.username == "alice.dev")).one()
    lecteur_role = db_session.scalars(select(Role).where(Role.name == "lecteur")).one()

    doc_id = "a" * 64
    doc = _create_document(db_session, doc_id=doc_id)
    db_session.add(DocumentRole(document_id=doc_id, role_id=lecteur_role.id))
    db_session.commit()

    conv_id = _create_conversation_with_citations(
        client,
        db_session,
        user=user,
        citations=[_make_citation(doc_id=doc_id, title="Loi Test", page=1)],
    )

    db_session.delete(doc)
    db_session.commit()

    resp = client.get(f"/conversations/{conv_id}", headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["available"] is False
    assert data["messages"][0]["answer"] is None


def test_get_conversation_hidden_cited_doc_returns_unavailable(
    access_env: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db_session = access_env
    user = db_session.scalars(select(User).where(User.username == "alice.dev")).one()
    lecteur_role = db_session.scalars(select(Role).where(Role.name == "lecteur")).one()

    doc_id = "b" * 64
    _create_document(db_session, doc_id=doc_id)
    db_session.add(DocumentRole(document_id=doc_id, role_id=lecteur_role.id))
    db_session.commit()

    conv_id = _create_conversation_with_citations(
        client,
        db_session,
        user=user,
        citations=[_make_citation(doc_id=doc_id, title="Document Restreint", page=2)],
    )

    monkeypatch.setattr(
        rights_mod,
        "get_retrieval",
        lambda: SimpleNamespace(
            hide=lambda _d: None, update_roles=lambda _d, _r: None, show=lambda _d: None
        ),
    )
    monkeypatch.setattr(
        rights_mod,
        "get_leak_index",
        lambda: SimpleNamespace(set_blocking=lambda *_a, **_kw: None),
    )
    monkeypatch.setattr(
        rights_mod,
        "get_audit",
        lambda: SimpleNamespace(log_action=lambda _a, _act, _det: None),
    )
    RealDocumentRights().set_document_roles(doc_id, ["editeur"])

    resp = client.get(f"/conversations/{conv_id}", headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["available"] is False
    assert data["messages"][0]["answer"] is None


def test_get_conversation_web_only_citations_stays_available(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    user = db_session.scalars(select(User).where(User.username == "alice.dev")).one()

    conv_id = _create_conversation_with_citations(
        client,
        db_session,
        user=user,
        citations=[
            _make_citation(
                doc_id=None,
                title="Source Web Officielle",
                url="https://example.ma/texte",
                page=None,
            )
        ],
    )

    resp = client.get(f"/conversations/{conv_id}", headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["available"] is True
    assert data["messages"][0]["answer"] is not None


# ---------------------------------------------------------------------------
# P5-31e/f: Admin self-protection & last active admin guards -> 422
# ---------------------------------------------------------------------------


def test_admin_cannot_deactivate_self(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    admin = db_session.scalars(select(User).where(User.username == "admin.user")).one()

    resp = client.patch(
        f"/admin/users/{admin.id}/active",
        json={"is_active": False},
        headers=_auth_headers(admin),
    )
    assert resp.status_code == 422


def test_admin_cannot_demote_self(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    admin = db_session.scalars(select(User).where(User.username == "admin.user")).one()
    lecteur_role = db_session.scalars(select(Role).where(Role.name == "lecteur")).one()

    resp = client.patch(
        f"/admin/users/{admin.id}/role",
        json={"role_id": lecteur_role.id},
        headers=_auth_headers(admin),
    )
    assert resp.status_code == 422


def test_cannot_deactivate_last_active_admin(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    admin1 = db_session.scalars(select(User).where(User.username == "admin.user")).one()
    admin_role = db_session.scalars(select(Role).where(Role.name == "admin")).one()
    admin2 = _create_user(db_session, "admin.second", admin_role, is_active=True)

    first_res = client.patch(
        f"/admin/users/{admin2.id}/active",
        json={"is_active": False},
        headers=_auth_headers(admin1),
    )
    assert first_res.status_code == 200

    last_res = client.patch(
        f"/admin/users/{admin1.id}/active",
        json={"is_active": False},
        headers=_auth_headers(admin1),
    )
    assert last_res.status_code == 422


def test_cannot_demote_last_active_admin(
    access_env: tuple[TestClient, Session],
) -> None:
    client, db_session = access_env
    admin1 = db_session.scalars(select(User).where(User.username == "admin.user")).one()
    admin_role = db_session.scalars(select(Role).where(Role.name == "admin")).one()
    lecteur_role = db_session.scalars(select(Role).where(Role.name == "lecteur")).one()
    admin2 = _create_user(db_session, "admin.second", admin_role, is_active=True)

    deactivate_res = client.patch(
        f"/admin/users/{admin2.id}/active",
        json={"is_active": False},
        headers=_auth_headers(admin1),
    )
    assert deactivate_res.status_code == 200

    demote_res = client.patch(
        f"/admin/users/{admin1.id}/role",
        json={"role_id": lecteur_role.id},
        headers=_auth_headers(admin1),
    )
    assert demote_res.status_code == 422
