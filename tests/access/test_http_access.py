from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.core.db.rights as rights_mod
import src.core.db.session as session_mod
from src.api.deps import get_current_user_context
from src.api.main import app
from src.core.contracts import registry
from src.core.contracts.enums import AccountRequestStatus, DocStatus, RoleName
from src.core.contracts.models import Answer, UserContext
from src.core.db.base import Base
from src.core.db.models import (
    AccountRequest,
    Conversation,
    Document,
    DocumentRole,
    Role,
    User,
)
from src.core.db.session import get_db
from src.core.security import hash_password


class _SpyRetrieval:
    def __init__(self) -> None:
        self.deleted_docs: list[str] = []

    def index(self, chunks: list[Any]) -> None:
        _ = chunks

    def search(self, query: str, ctx: UserContext, top_k: int | None = None) -> list[Any]:
        _ = (query, ctx, top_k)
        return []

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        _ = (doc_id, roles)

    def hide(self, doc_id: str) -> None:
        _ = doc_id

    def show(self, doc_id: str) -> None:
        _ = doc_id

    def delete(self, doc_id: str) -> None:
        self.deleted_docs.append(doc_id)


class _SpyIngestion:
    def __init__(self) -> None:
        self.deleted_docs: list[str] = []

    def ingest(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def delete(self, doc_id: str) -> None:
        self.deleted_docs.append(doc_id)


class _SpyIngestion:
    def __init__(self) -> None:
        self.deleted_docs: list[str] = []

    def ingest(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def delete(self, doc_id: str) -> None:
        self.deleted_docs.append(doc_id)


class _SpyLeakIndex:
    def __init__(self) -> None:
        self.deleted_docs: list[str] = []

    def register(self, doc_id: str, text: str) -> None:
        _ = (doc_id, text)

    def set_blocking(self, doc_id: str, blocking: bool) -> None:
        _ = (doc_id, blocking)

    def delete(self, doc_id: str) -> None:
        self.deleted_docs.append(doc_id)


@pytest.fixture
def http_env(
    lecteur_ctx: UserContext,
    other_lecteur_ctx: UserContext,
    editeur_ctx: UserContext,
    admin_ctx: UserContext,
    fake_audit: Any,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    current_holder: dict[str, UserContext] = {"ctx": lecteur_ctx}
    db = TestingSessionLocal()

    r_lecteur = Role(id=1, name=RoleName.LECTEUR.value, description="Lecteur", web_enabled=True)
    r_editeur = Role(id=2, name=RoleName.EDITEUR.value, description="Editeur", web_enabled=True)
    r_admin = Role(id=3, name=RoleName.ADMIN.value, description="Admin", web_enabled=True)
    db.add_all([r_lecteur, r_editeur, r_admin])
    db.flush()

    u_lecteur = User(
        id=lecteur_ctx.user_id,
        username=lecteur_ctx.username,
        hashed_password=hash_password("secret123"),
        full_name="Lecteur User",
        is_active=True,
        role_id=r_lecteur.id,
    )
    u_other = User(
        id=other_lecteur_ctx.user_id,
        username=other_lecteur_ctx.username,
        hashed_password=hash_password("secret123"),
        full_name="Other Lecteur",
        is_active=True,
        role_id=r_lecteur.id,
    )
    u_editeur = User(
        id=editeur_ctx.user_id,
        username=editeur_ctx.username,
        hashed_password=hash_password("secret123"),
        full_name="Editeur User",
        is_active=True,
        role_id=r_editeur.id,
    )
    u_admin = User(
        id=admin_ctx.user_id,
        username=admin_ctx.username,
        hashed_password=hash_password("secret123"),
        full_name="Admin User",
        is_active=True,
        role_id=r_admin.id,
    )
    db.add_all([u_lecteur, u_other, u_editeur, u_admin])
    db.commit()

    spy_retrieval = _SpyRetrieval()
    spy_ingestion = _SpyIngestion()
    spy_leak = _SpyLeakIndex()
    registry.override("retrieval", spy_retrieval)
    registry.override("ingestion", spy_ingestion)
    registry.override("leak_index", spy_leak)

    monkeypatch.setattr(session_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(rights_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(rights_mod, "get_retrieval", lambda: spy_retrieval)
    monkeypatch.setattr(rights_mod, "get_leak_index", lambda: spy_leak)
    monkeypatch.setattr(rights_mod, "get_audit", lambda: fake_audit)
    monkeypatch.setattr("src.api.main.init_db", lambda: None)

    def _override_db():
        yield db

    def _override_ctx() -> UserContext:
        return current_holder["ctx"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user_context] = _override_ctx

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield {
            "client": client,
            "db": db,
            "set_ctx": lambda c: current_holder.__setitem__("ctx", c),
            "lecteur": lecteur_ctx,
            "other": other_lecteur_ctx,
            "editeur": editeur_ctx,
            "admin": admin_ctx,
            "retrieval": spy_retrieval,
            "ingestion": spy_ingestion,
            "leak": spy_leak,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_documents_sha256_id_visibility_and_delete(http_env: dict[str, Any]) -> None:
    client: TestClient = http_env["client"]
    db: Session = http_env["db"]
    set_ctx = http_env["set_ctx"]

    sha_doc_id = "a" * 64
    private_doc_id = "b" * 64

    pub_doc = Document(
        id=sha_doc_id,
        title="Loi Publique",
        source_file="loi.pdf",
        owner_id=None,
        status=DocStatus.READY.value,
        file_hash="1" * 64,
    )
    priv_doc = Document(
        id=private_doc_id,
        title="Note Privee",
        source_file="note.txt",
        owner_id=http_env["other"].user_id,
        status=DocStatus.READY.value,
        file_hash="2" * 64,
    )
    db.add_all([pub_doc, priv_doc])
    db.flush()
    db.add(DocumentRole(document_id=sha_doc_id, role_id=1))
    db.commit()

    set_ctx(http_env["lecteur"])
    status_res = client.get(f"/documents/{sha_doc_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["doc_id"] == sha_doc_id

    list_res = client.get("/documents")
    assert list_res.status_code == 200
    doc_ids = [item["doc_id"] for item in list_res.json()]
    assert sha_doc_id in doc_ids
    assert private_doc_id not in doc_ids

    forbid_priv_status = client.get(f"/documents/{private_doc_id}/status")
    assert forbid_priv_status.status_code == 404

    forbid_del = client.delete(f"/documents/{sha_doc_id}")
    assert forbid_del.status_code == 404

    set_ctx(http_env["admin"])
    del_res = client.delete(f"/documents/{sha_doc_id}")
    assert del_res.status_code == 204
    assert sha_doc_id in http_env["ingestion"].deleted_docs
    assert sha_doc_id in http_env["ingestion"].deleted_docs


def test_admin_account_request_approve_and_reject(http_env: dict[str, Any]) -> None:
    client: TestClient = http_env["client"]
    db: Session = http_env["db"]
    set_ctx = http_env["set_ctx"]

    set_ctx(http_env["lecteur"])
    assert client.get("/admin/users").status_code == 403

    req_approve_id = uuid4()
    req_reject_id = uuid4()
    db.add_all(
        [
            AccountRequest(
                id=req_approve_id,
                username="nouveau_lecteur",
                hashed_password=hash_password("pw123456"),
                full_name="Nouveau Lecteur",
                status=AccountRequestStatus.PENDING.value,
                created_at=datetime.now(UTC),
            ),
            AccountRequest(
                id=req_reject_id,
                username="demande_rejetee",
                hashed_password=hash_password("pw123456"),
                full_name="Demande Rejetee",
                status=AccountRequestStatus.PENDING.value,
                created_at=datetime.now(UTC),
            ),
        ]
    )
    db.commit()

    set_ctx(http_env["admin"])
    approve_res = client.post(
        f"/admin/account-requests/{req_approve_id}/approve",
        json={"role_id": 1},
    )
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["status"] == AccountRequestStatus.APPROVED.value
    assert approve_data["decided_by"] == str(http_env["admin"].user_id)
    assert approve_data["decided_at"] is not None

    assert (
        client.post(
            f"/admin/account-requests/{req_approve_id}/approve",
            json={"role_id": 1},
        ).status_code
        == 409
    )

    reject_res = client.post(f"/admin/account-requests/{req_reject_id}/reject")
    assert reject_res.status_code == 200
    reject_data = reject_res.json()
    assert reject_data["status"] == AccountRequestStatus.REJECTED.value
    assert reject_data["decided_by"] == str(http_env["admin"].user_id)
    assert reject_data["decided_at"] is not None


def test_conversations_persistence_and_ownership(http_env: dict[str, Any]) -> None:
    client: TestClient = http_env["client"]
    db: Session = http_env["db"]
    set_ctx = http_env["set_ctx"]

    set_ctx(http_env["lecteur"])
    create_res = client.post("/conversations", json={})
    assert create_res.status_code == 201
    conv_id = create_res.json()["conversation_id"]
    assert create_res.json()["title"] is None

    answer_payload = Answer(
        status="answered",
        text="المادة 1 واضحة [1].",
        citations=[],
        confidence=0.9,
        language="ar",
    ).model_dump(mode="json")

    msg_res = client.post(
        f"/conversations/{conv_id}/messages",
        json={"question": "ما هي المادة 1؟", "answer": answer_payload},
    )
    assert msg_res.status_code == 201
    msg_data = msg_res.json()
    assert msg_data["position"] == 1
    assert msg_data["available"] is True

    detail_res = client.get(f"/conversations/{conv_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["title"] == "ما هي المادة 1؟"
    assert len(detail["messages"]) == 1

    set_ctx(http_env["other"])
    assert client.get(f"/conversations/{conv_id}").status_code == 404

    conv_row = db.get(Conversation, UUID(conv_id))
    assert conv_row is not None
    assert len(conv_row.messages) == 1

