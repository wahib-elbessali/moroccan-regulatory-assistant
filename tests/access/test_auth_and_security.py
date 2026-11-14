"""End-to-end security, authentication, RBAC, and middleware tests for P5."""

from collections.abc import Generator
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.contracts.enums import AccountRequestStatus
from src.core.db.base import Base
from src.core.db.models import AccountRequest, Role, User
from src.core.db.session import get_db
from src.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite database seeded with default roles and a user."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()

    admin_role = Role(id=1, name="admin", web_enabled=True)
    user_role = Role(id=2, name="user", web_enabled=False)
    session.add_all([admin_role, user_role])
    session.flush()

    active_user = User(
        id=uuid4(),
        username="alice.dev",
        hashed_password=get_password_hash("StrongPass123!"),
        full_name="Alice Developer",
        role_id=user_role.id,
        is_active=True,
    )
    disabled_user = User(
        id=uuid4(),
        username="bob.disabled",
        hashed_password=get_password_hash("StrongPass123!"),
        full_name="Bob Disabled",
        role_id=user_role.id,
        is_active=False,
    )
    session.add_all([active_user, disabled_user])
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
# Password hashing & JWT token round-trip
# ---------------------------------------------------------------------------


def test_argon2_password_hashing_and_verification() -> None:
    raw = "MySecurePassword99!"
    hashed = get_password_hash(raw)
    assert hashed != raw
    assert hashed.startswith("$argon2")
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_create_and_decode_roundtrip() -> None:
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


def test_invalid_request_id_header_generates_fresh_uuid(client: TestClient) -> None:
    res = client.get("/health", headers={"X-Request-ID": "not-a-uuid"})
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert res.headers["X-Request-ID"] != "not-a-uuid"


# ---------------------------------------------------------------------------
# /auth/login & /auth/me (P5-15 to P5-18)
# ---------------------------------------------------------------------------


def test_login_success_and_me_endpoint(client: TestClient) -> None:
    login_res = client.post(
        "/auth/login",
        json={"username": "alice.dev", "password": "StrongPass123!"},
    )
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20

    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["username"] == "alice.dev"
    assert me_data["role"] == "user"
    assert me_data["web_available"] is False


def test_login_rejects_wrong_password_and_inactive_user(client: TestClient) -> None:
    bad_pw = client.post(
        "/auth/login",
        json={"username": "alice.dev", "password": "WrongPassword!"},
    )
    assert bad_pw.status_code == 401
    assert bad_pw.json() == {"code": "unauthenticated", "message": "wrong username or password"}

    inactive = client.post(
        "/auth/login",
        json={"username": "bob.disabled", "password": "StrongPass123!"},
    )
    assert inactive.status_code == 401
    assert inactive.json()["code"] == "unauthenticated"


def test_me_requires_valid_bearer_token(client: TestClient) -> None:
    no_auth = client.get("/auth/me")
    assert no_auth.status_code == 401

    bad_auth = client.get("/auth/me", headers={"Authorization": "Bearer invalid.jwt.token"})
    assert bad_auth.status_code == 401


# ---------------------------------------------------------------------------
# /auth/account-requests (P5-38 to P5-40)
# ---------------------------------------------------------------------------


def test_account_request_creation_and_duplicate_conflict(
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
    data = res.json()
    assert data["status"] == AccountRequestStatus.PENDING.value
    assert "request_id" in data

    # Stored password must be hashed (never plain text)
    stored = db_session.query(AccountRequest).filter_by(username="charlie.new").one()
    assert stored.hashed_password != "ValidPassword123!"
    assert stored.hashed_password.startswith("$argon2")

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
    assert dup.json()["code"] == "conflict"


def test_account_request_validation_errors(client: TestClient) -> None:
    short_pw = client.post(
        "/auth/account-requests",
        json={
            "username": "valid.user",
            "password": "123",
            "full_name": "Valid Name",
        },
    )
    assert short_pw.status_code == 422
    assert short_pw.json()["code"] == "invalid_input"
