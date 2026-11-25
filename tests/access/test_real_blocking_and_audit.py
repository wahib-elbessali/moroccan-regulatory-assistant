"""integration tests: real HttpLeakIndex.set_blocking + RealAudit + RealDocumentRights (T9, T10, T19, T43, T44)."""

import json
from collections.abc import Generator
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.core.audit as audit_mod
import src.core.db.rights as rights_mod
import src.core.db.session as session_mod
from src.core.audit import RealAudit
from src.core.contracts.enums import AuditAction, DocStatus
from src.core.contracts.errors import InvalidInput, ServiceError
from src.core.contracts.models import UserContext
from src.core.db.base import Base
from src.core.db.models import AuditLog, Document, Role, User
from src.core.db.rights import RealDocumentRights, audit_actor_var, list_visible_documents
from src.core.leak.index import HttpLeakIndex
from src.core.security import get_password_hash, request_id_var


@pytest.fixture()
def real_db_and_audit(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    """Isolated SQLite database wired to RealDocumentRights and RealAudit."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(session_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(rights_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(audit_mod, "SessionLocal", TestingSessionLocal)

    real_audit_instance = RealAudit()
    monkeypatch.setattr(rights_mod, "get_audit", lambda: real_audit_instance)

    session = TestingSessionLocal()
    admin_role = Role(id=1, name="admin", web_enabled=True)
    editeur_role = Role(id=2, name="editeur", web_enabled=True)
    lecteur_role = Role(id=3, name="lecteur", web_enabled=False)
    session.add_all([admin_role, editeur_role, lecteur_role])
    session.flush()

    admin_user = User(
        id=uuid4(),
        username="admin.jalon2",
        hashed_password=get_password_hash(f"test-pw-{uuid4()}"),
        full_name="Admin Jalon 2",
        role_id=admin_role.id,
        is_active=True,
    )
    session.add(admin_user)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_real_set_blocking_and_audit_flow_t9_t44(
    real_db_and_audit: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T9 + T44: Real HttpLeakIndex (/blocking) + RealAudit + RealDocumentRights across internal <-> public transitions."""
    blocking_requests: list[dict[str, object]] = []
    auth_headers_seen: list[str] = []

    def _web_search_handler(request: httpx.Request) -> httpx.Response:
        auth_headers_seen.append(request.headers.get("Authorization", ""))
        if request.url.path == "/blocking":
            payload = json.loads(request.content.decode("utf-8"))
            blocking_requests.append(payload)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    mock_http = httpx.Client(
        base_url="http://web-search:8090",
        transport=httpx.MockTransport(_web_search_handler),
    )
    real_leak = HttpLeakIndex(
        base_url="http://web-search:8090",
        token="test-leak-token",
        key=b"0123456789abcdef0123456789abcdef",
        client=mock_http,
    )
    fake_retrieval = SimpleNamespace(
        hide=lambda doc_id: None,
        update_roles=lambda doc_id, roles: None,
        show=lambda doc_id: None,
    )
    monkeypatch.setattr(rights_mod, "get_leak_index", lambda: real_leak)
    monkeypatch.setattr(rights_mod, "get_retrieval", lambda: fake_retrieval)

    doc_id = "f" * 64
    real_db_and_audit.add(
        Document(
            id=doc_id,
            title="Loi 09-08 Protection des Données",
            source_file="loi_09_08.pdf",
            owner_id=None,
            status=DocStatus.INDEXED.value,
            file_hash="e" * 64,
        )
    )
    real_db_and_audit.commit()

    admin = real_db_and_audit.scalars(select(User).where(User.username == "admin.jalon2")).one()
    req_id = uuid4()
    rights = RealDocumentRights()

    lecteur_ctx = UserContext(
        user_id=uuid4(), username="citizen", role="lecteur", web_enabled=False, request_id=req_id
    )
    editeur_ctx = UserContext(
        user_id=uuid4(), username="editor", role="editeur", web_enabled=True, request_id=req_id
    )

    # Step 1: Publish as internal (["editeur"]) -> blocking=True sent to web-search
    rid_tok = request_id_var.set(req_id)
    actor_tok = audit_actor_var.set(admin.id)
    try:
        rights.set_document_roles(doc_id, ["editeur"])
    finally:
        audit_actor_var.reset(actor_tok)
        request_id_var.reset(rid_tok)

    assert blocking_requests[-1] == {"doc_id": doc_id, "blocking": True}
    assert auth_headers_seen[-1] == "Bearer test-leak-token"
    real_db_and_audit.expire_all()
    assert list_visible_documents(real_db_and_audit, lecteur_ctx) == []
    assert [d.id for d in list_visible_documents(real_db_and_audit, editeur_ctx)] == [doc_id]

    # Step 2 (T9): Switch to public (["lecteur", "editeur"]) -> blocking=False sent to web-search
    rights.set_document_roles(doc_id, ["lecteur", "editeur"])
    assert blocking_requests[-1] == {"doc_id": doc_id, "blocking": False}
    real_db_and_audit.expire_all()
    assert [d.id for d in list_visible_documents(real_db_and_audit, lecteur_ctx)] == [doc_id]

    # Step 3 (T9): Switch back to internal (["editeur"]) -> blocking=True again
    rights.set_document_roles(doc_id, ["editeur"])
    assert blocking_requests[-1] == {"doc_id": doc_id, "blocking": True}
    real_db_and_audit.expire_all()
    assert list_visible_documents(real_db_and_audit, lecteur_ctx) == []

    # Step 4 (T44): Verify RealAudit persisted rows in PostgreSQL/SQLite with exact request_id
    audit_rows = real_db_and_audit.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.ADMIN_UPDATE.value)
    ).all()
    assert len(audit_rows) == 3
    assert audit_rows[0].request_id == req_id
    assert audit_rows[0].user_id == admin.id


def test_set_document_roles_failure_marks_failed_and_audits_t10_t19_t43(
    real_db_and_audit: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T10, T19, T43: If leak_index or retrieval fails during publication, status becomes failed and is audited."""
    # Simulate web-search returning 503 during set_blocking
    failing_http = httpx.Client(
        base_url="http://web-search:8090",
        transport=httpx.MockTransport(lambda req: httpx.Response(503)),
    )
    failing_leak = HttpLeakIndex(
        base_url="http://web-search:8090",
        token="test-leak-token",
        key=b"0123456789abcdef0123456789abcdef",
        client=failing_http,
    )
    fake_retrieval = SimpleNamespace(
        hide=lambda doc_id: None,
        update_roles=lambda doc_id, roles: None,
        show=lambda doc_id: None,
    )
    monkeypatch.setattr(rights_mod, "get_leak_index", lambda: failing_leak)
    monkeypatch.setattr(rights_mod, "get_retrieval", lambda: fake_retrieval)

    doc_id = "1" * 64
    real_db_and_audit.add(
        Document(
            id=doc_id,
            title="Doc Failing Leak Index",
            source_file="fail.pdf",
            owner_id=None,
            status=DocStatus.INDEXED.value,
            file_hash="2" * 64,
        )
    )
    real_db_and_audit.commit()

    rights = RealDocumentRights()
    with pytest.raises(ServiceError):
        rights.set_document_roles(doc_id, ["lecteur", "editeur"])

    real_db_and_audit.expire_all()
    doc = real_db_and_audit.get(Document, doc_id)
    assert doc is not None
    assert doc.status == DocStatus.FAILED.value

    # T19: Calling set_document_roles on a failed document raises InvalidInput (422) and leaves status unchanged
    with pytest.raises(InvalidInput, match="not indexed"):
        rights.set_document_roles(doc_id, ["editeur"])
    real_db_and_audit.expire_all()
    assert real_db_and_audit.get(Document, doc_id).status == DocStatus.FAILED.value  # type: ignore[union-attr]
