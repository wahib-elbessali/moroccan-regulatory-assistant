"""End-to-end security, authentication, RBAC, rights, and middleware tests for P5."""

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.core.config as config_mod
import src.core.db.rights as rights_mod
import src.core.db.session as session_mod
from src.api.deps import require_admin, require_roles
from src.api.main import app
from src.api.routes import auth as auth_route
from src.core.contracts.enums import AccountRequestStatus, DocStatus
from src.core.contracts.errors import Forbidden, InvalidInput
from src.core.contracts.models import UserContext
from src.core.db.base import Base
from src.core.db.models import Document, DocumentRole, Role, User
from src.core.db.rights import (
    RealDocumentRights,
    approve_account_request,
    audit_actor_var,
    list_visible_documents,
    reject_account_request,
)
from src.core.db.session import get_db
from src.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite database seeded with roles and test users."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(session_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(rights_mod, "SessionLocal", TestingSessionLocal)
    auth_route._failed_attempts.clear()

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
    disabled_user = User(
        id=uuid4(),
        username="bob.disabled",
        hashed_password=get_password_hash("StrongPass123!"),
        full_name="Bob Disabled",
        role_id=lecteur_role.id,
        is_active=False,
    )
    session.add_all([admin_user, active_user, disabled_user])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """FastAPI TestClient wired to the isolated test DB session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    monkeypatch.setattr("src.api.main.init_db", lambda: None)
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Password hashing & JWT token round-trip (including .env-only secret)
# ---------------------------------------------------------------------------


def test_argon2_password_hashing_and_verification() -> None:
    raw = "MySecurePassword99!"
    hashed = get_password_hash(raw)
    assert hashed != raw
    assert hashed.startswith("$argon2")
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_create_and_decode_from_dotenv_when_env_var_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure JWT create/decode works when JWT_SECRET is absent from os.environ and read from .env."""
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "POSTGRES_PASSWORD=dotenv-pg-pass\n"
        "JWT_SECRET=dotenv-only-secret-key-at-least-32-chars\n"
        "ADMIN_USERNAME=admin\n"
        "ADMIN_PASSWORD=dotenv-admin-pass\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_mod.cfg, "_instance", None)

    uid = str(uuid4())
    token = create_access_token({"sub": uid})
    payload = decode_access_token(token)
    assert payload["sub"] == uid


def test_jwt_decode_rejects_tampered_token() -> None:
    token = create_access_token({"sub": str(uuid4())})
    tampered = f"{token}corrupted"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)


# ---------------------------------------------------------------------------
# Middleware X-Request-ID & Healthcheck
# ---------------------------------------------------------------------------


def test_health_and_request_id_echo(client: TestClient) -> None:
    custom_rid = str(uuid4())
    res = client.get("/health", headers={"X-Request-ID": custom_rid})
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert res.headers["X-Request-ID"] == custom_rid


# ---------------------------------------------------------------------------
# /auth/login, brute-force lockout & /auth/me (P5-15 to P5-18)
# ---------------------------------------------------------------------------


def test_login_success_and_me_endpoint(client: TestClient) -> None:
    login_res = client.post(
        "/auth/login",
        json={"username": "alice.dev", "password": "StrongPass123!"},
    )
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["token_type"] == "bearer"

    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["username"] == "alice.dev"
    assert me_data["role"] == "lecteur"
    assert me_data["web_available"] is False


def test_login_lockout_after_max_failed_attempts(client: TestClient) -> None:
    for _ in range(5):
        res = client.post(
            "/auth/login",
            json={"username": "alice.dev", "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # Even with the right password, account is temporarily locked out
    locked_res = client.post(
        "/auth/login",
        json={"username": "alice.dev", "password": "StrongPass123!"},
    )
    assert locked_res.status_code == 401


def test_login_rejects_inactive_user(client: TestClient) -> None:
    inactive = client.post(
        "/auth/login",
        json={"username": "bob.disabled", "password": "StrongPass123!"},
    )
    assert inactive.status_code == 401


# ---------------------------------------------------------------------------
# RBAC dependencies (require_roles / require_admin)
# ---------------------------------------------------------------------------


def test_require_admin_and_require_roles() -> None:
    admin_ctx = UserContext(
        user_id=uuid4(),
        username="admin.user",
        role="admin",
        web_enabled=True,
        request_id=uuid4(),
    )
    lecteur_ctx = UserContext(
        user_id=uuid4(),
        username="alice.dev",
        role="lecteur",
        web_enabled=False,
        request_id=uuid4(),
    )

    assert require_admin(admin_ctx) == admin_ctx
    with pytest.raises(Forbidden):
        require_admin(lecteur_ctx)

    editor_dep = require_roles(["admin", "editeur"])
    with pytest.raises(Forbidden):
        editor_dep(lecteur_ctx)


# ---------------------------------------------------------------------------
# /auth/account-requests & admin approval/rejection (P5-38 to P5-42)
# ---------------------------------------------------------------------------


def test_account_request_lifecycle_approve_and_reject(
    client: TestClient,
    db_session: Session,
) -> None:
    res = client.post(
        "/auth/account-requests",
        json={
            "username": "charlie.new",
            "password": "ValidPassword123!",
            "full_name": "Charlie Newcomer",
        },
    )
    assert res.status_code == 202
    req_id = res.json()["request_id"]

    # Duplicate pending username -> 409 Conflict
    dup = client.post(
        "/auth/account-requests",
        json={
            "username": "charlie.new",
            "password": "ValidPassword123!",
            "full_name": "Charlie Duplicate",
        },
    )
    assert dup.status_code == 409

    admin = db_session.scalars(select(User).where(User.username == "admin.user")).one()
    created_user = approve_account_request(
        db_session,
        request_id=(
            jwt.utils.base64url_decode  # type: ignore[arg-type]
            if False
            else __import__("uuid").UUID(req_id)
        ),
        role_name="editeur",
        decided_by=admin.id,
    )
    assert created_user.username == "charlie.new"
    assert created_user.role.name == "editeur"

    # Second request -> reject
    res2 = client.post(
        "/auth/account-requests",
        json={
            "username": "dana.reject",
            "password": "ValidPassword123!",
            "full_name": "Dana Reject",
        },
    )
    assert res2.status_code == 202
    req2_id = __import__("uuid").UUID(res2.json()["request_id"])
    rejected = reject_account_request(db_session, request_id=req2_id, decided_by=admin.id)
    assert rejected.status == AccountRequestStatus.REJECTED.value


# ---------------------------------------------------------------------------
# RealDocumentRights.set_document_roles & list_visible_documents
# ---------------------------------------------------------------------------


def test_set_document_roles_updates_db_leak_index_and_visibility(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    fake_retrieval = SimpleNamespace(
        hide=lambda doc_id: calls.append(("hide", doc_id)),
        update_roles=lambda doc_id, roles: calls.append(("update_roles", list(roles))),
        show=lambda doc_id: calls.append(("show", doc_id)),
    )
    fake_leak = SimpleNamespace(
        set_blocking=lambda doc_id, blocking: calls.append(("set_blocking", blocking)),
    )
    fake_audit = SimpleNamespace(
        log_action=lambda actor, action, details: calls.append(("audit", (actor, action, details))),
    )

    monkeypatch.setattr(rights_mod, "get_retrieval", lambda: fake_retrieval)
    monkeypatch.setattr(rights_mod, "get_leak_index", lambda: fake_leak)
    monkeypatch.setattr(rights_mod, "get_audit", lambda: fake_audit)

    doc_id = "a" * 64
    doc = Document(
        id=doc_id,
        title="Code du Travail",
        source_file="travail.pdf",
        owner_id=None,
        status=DocStatus.INDEXED.value,
        file_hash="b" * 64,
    )
    db_session.add(doc)
    db_session.commit()

    rights = RealDocumentRights()
    admin = db_session.scalars(select(User).where(User.username == "admin.user")).one()

    # 1. Publish as internal only (['editeur']) -> leak blocking must be True
    token = audit_actor_var.set(admin.id)
    try:
        out = rights.set_document_roles(doc_id, ["editeur"])
    finally:
        audit_actor_var.reset(token)

    assert out == {"doc_id": doc_id, "status": DocStatus.READY.value}
    assert ("set_blocking", True) in calls

    # Lecteur cannot see internal-only document, editeur can
    lecteur_ctx = UserContext(
        user_id=uuid4(), username="alice", role="lecteur", web_enabled=False, request_id=uuid4()
    )
    editeur_ctx = UserContext(
        user_id=uuid4(), username="ed", role="editeur", web_enabled=True, request_id=uuid4()
    )
    db_session.expire_all()
    assert list_visible_documents(db_session, lecteur_ctx) == []
    assert [d.id for d in list_visible_documents(db_session, editeur_ctx)] == [doc_id]

    # 2. Switch to public (['lecteur', 'editeur']) -> leak blocking must be False
    calls.clear()
    rights.set_document_roles(doc_id, ["lecteur", "editeur"])
    assert ("set_blocking", False) in calls
    db_session.expire_all()
    assert [d.id for d in list_visible_documents(db_session, lecteur_ctx)] == [doc_id]
    assert db_session.query(DocumentRole).filter_by(document_id=doc_id).count() == 2


def test_set_document_roles_rejects_unindexed_document(db_session: Session) -> None:
    doc_id = "c" * 64
    db_session.add(
        Document(
            id=doc_id,
            title="Unindexed Doc",
            source_file="draft.pdf",
            owner_id=None,
            status=DocStatus.RECEIVED.value,
            file_hash="d" * 64,
        )
    )
    db_session.commit()

    rights = RealDocumentRights()
    with pytest.raises(InvalidInput, match="not indexed"):
        rights.set_document_roles(doc_id, ["editeur"])
