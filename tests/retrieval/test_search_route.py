"""Tests of ``POST /search`` (P2-28), the route in ``src/api/routes/search.py``.

The route is thin on purpose, so these tests only check what belongs to it: that the body is
read, that the context comes from P5's authentication and nothing else, that ``top_k`` travels
unchanged, that the passages are handed back untouched, and that each failure reaches the client
in the project's one error format. What the pipeline *does* is covered elsewhere and is not
repeated here — ``tests/retrieval/test_search.py`` (RRF, re-ranking, fallbacks, the P2-29 line),
``tests/retrieval/test_access.py`` (T1–T4, T13 on real Qdrant) and
``tests/contracts/test_retrieval.py`` (T1–T8, T10, T12 on both implementations).

Three groups, in this order:

1. **The route**, with ``get_current_user_context`` overridden (R1–R8, R11–R14). The
   implementation behind the registry is the real ``FakeRetrieval`` wherever the assertion is
   about behaviour, so a 422 is produced by the agreed ``InvalidInput`` mechanism (P2-11) and not
   by a double that merely agrees with it; a recording double is used only where the assertion is
   about *what the route passed on*.
2. **The real authentication dependency** (R9, R10), over a SQLite database. The override of
   group 1 proves nothing about authentication, so these tests do not use it: they send real
   bearer tokens through ``src.core.security.get_current_user_context``.
3. **The real application**, to check the route is mounted where 00-shared §8 says.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from p2_helpers import make_doc
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routes.search import SearchRequest, router
from src.core.contracts import (
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    AppError,
    Chunk,
    Passage,
    ServiceError,
    UserContext,
    registry,
)
from src.core.contracts.fakes.retrieval import FakeRetrieval
from src.core.db.base import Base
from src.core.db.models import Role, User
from src.core.db.session import get_db
from src.core.security import create_access_token, get_current_user_context, get_password_hash

# The fake scores a chunk by how many distinct query words its text, title and article contain,
# so a text built from the query's own words is certain to match. QUERY and the texts below are
# whole, distinctive strings: R14 asserts that none of them reaches a log record.
QUERY = "شروط كفالة الطفل المهمل"
QUERY_WORDS = QUERY.split()
PUBLIC_TEXT = " ".join(QUERY_WORDS)
INTERNAL_TEXT = " ".join(QUERY_WORDS[:3]) + " مذكرة داخلية"
PRIVATE_TEXT = " ".join(QUERY_WORDS[:2]) + " ملف شخصي"
NO_MATCH_QUERY = "موضوع بعيد تماما عن الملف"


# --- Doubles ----------------------------------------------------------------------------------


class SpyRetrieval:
    """Records every ``search`` call; answers with fixed passages, or raises.

    Only used where the assertion is about the arguments the route passed on, or about an error
    coming back out of the pipeline. Everything about *behaviour* is asserted on the real
    ``FakeRetrieval`` instead.
    """

    def __init__(
        self, passages: list[Passage] | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[tuple[str, UserContext, int | None]] = []
        self._passages = passages or []
        self._error = error

    def search(self, query: str, ctx: UserContext, top_k: int | None = None) -> list[Passage]:
        self.calls.append((query, ctx, top_k))
        if self._error is not None:
            raise self._error
        return self._passages


def passage(text: str = PUBLIC_TEXT) -> Passage:
    """One ``Passage`` over a real ``Chunk``, so the response model is exercised for real."""
    chunk: Chunk = make_doc("spy", texts=[text], roles=PUBLIC_ROLES)[0]
    return Passage(chunk=chunk, score=1.5, rank=1)


# --- Group 1: the route, authentication overridden --------------------------------------------


def build_app(ctx: UserContext) -> FastAPI:
    """The router alone, with ``ctx`` as the authenticated user.

    The ``AppError`` handler is the one of ``src/api/main.py`` (P5-05): same body, same status.
    Mounting only the router keeps these tests independent of the database and of the lifespan,
    which ``test_route_is_mounted_in_the_application`` covers separately.
    """
    app = FastAPI()
    app.include_router(router, prefix="/search")
    app.dependency_overrides[get_current_user_context] = lambda: ctx

    @app.exception_handler(AppError)
    async def _app_error(_request: Any, exc: AppError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.http_status)

    return app


@pytest.fixture
def fake_retrieval(tmp_path: Any) -> FakeRetrieval:
    """``FakeRetrieval`` over ``tmp_path``, installed in the registry.

    ``tmp_path`` keeps the project's ``data/processed`` untouched. The autouse ``_fresh_registry``
    fixture of ``tests/conftest.py`` removes the override after each test.
    """
    impl = FakeRetrieval(data_dir=tmp_path)
    registry.override("retrieval", impl)
    return impl


@pytest.fixture
def client(lecteur_ctx: UserContext, fake_retrieval: FakeRetrieval) -> TestClient:
    return TestClient(build_app(lecteur_ctx))


def spy_client(ctx: UserContext, spy: SpyRetrieval) -> TestClient:
    registry.override("retrieval", spy)
    return TestClient(build_app(ctx))


def published(impl: FakeRetrieval, chunks: list[Chunk]) -> list[Chunk]:
    """Indexes a document and shows it: ``index`` stores chunks hidden (P2-06)."""
    impl.index(chunks)
    impl.show(chunks[0].doc_id)
    return chunks


# --- R1: the happy path -----------------------------------------------------------------------


def test_r1_valid_request_returns_200_and_a_list_of_passages(
    client: TestClient, fake_retrieval: FakeRetrieval
) -> None:
    """R1: a search that matches answers 200 with a JSON list of ``Passage`` objects."""
    chunks = published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT], roles=PUBLIC_ROLES))

    response = client.post("/search", json={"query": QUERY, "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    # Parses back into the shared model: the route changed none of its fields (00-shared §5.3).
    returned = [Passage.model_validate(item) for item in body]
    assert returned[0].chunk.chunk_id == chunks[0].chunk_id
    assert returned[0].rank == 1
    assert body[0].keys() == {"chunk", "score", "rank"}


def test_r1_ranks_and_scores_are_handed_back_untouched(
    client: TestClient, fake_retrieval: FakeRetrieval
) -> None:
    """The route never reorders or renumbers: ranks are 1, 2, 3… and scores do not increase."""
    published(
        fake_retrieval,
        make_doc(
            "public",
            texts=[PUBLIC_TEXT, " ".join(QUERY_WORDS[:2]), QUERY_WORDS[0]],
            roles=PUBLIC_ROLES,
        ),
    )

    body = client.post("/search", json={"query": QUERY}).json()

    assert [item["rank"] for item in body] == list(range(1, len(body) + 1))
    scores = [item["score"] for item in body]
    assert scores == sorted(scores, reverse=True)


def test_trailing_slash_is_the_same_route(
    client: TestClient, fake_retrieval: FakeRetrieval
) -> None:
    """``POST /search/`` answers like ``POST /search`` (the convention of ask.py)."""
    published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT], roles=PUBLIC_ROLES))

    direct = client.post("/search", json={"query": QUERY})
    slashed = client.post("/search/", json={"query": QUERY})

    assert slashed.status_code == direct.status_code == 200
    assert slashed.json() == direct.json()


# --- R2, R3, R4: what the route passes on -----------------------------------------------------


def test_r2_query_and_top_k_are_forwarded_unchanged(lecteur_ctx: UserContext) -> None:
    """R2: the body's ``query`` and ``top_k`` reach ``search`` exactly as they arrived."""
    spy = SpyRetrieval([passage()])

    spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY, "top_k": 7})

    assert spy.calls == [(QUERY, lecteur_ctx, 7)]


def test_r3_missing_top_k_is_forwarded_as_none(lecteur_ctx: UserContext) -> None:
    """R3: ``top_k`` omitted arrives as ``None``, which is what means ``retrieval.top_k_final``
    for ``Retrieval.search`` (00-shared §6.3). The route holds no default of its own."""
    spy = SpyRetrieval()

    spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY})

    assert spy.calls == [(QUERY, lecteur_ctx, None)]


def test_r3_explicit_null_top_k_is_also_the_default(lecteur_ctx: UserContext) -> None:
    """``"top_k": null`` is the same request as no ``top_k`` at all."""
    spy = SpyRetrieval()

    spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY, "top_k": None})

    assert spy.calls == [(QUERY, lecteur_ctx, None)]


def test_r3_the_default_really_is_top_k_final(lecteur_ctx: UserContext, tmp_path: Any) -> None:
    """R3, end to end: with no ``top_k``, at most ``retrieval.top_k_final`` passages come back.

    ``top_k_final`` is set to 2 here, against 5 matching chunks, so the cap is visible without
    depending on ``config.yaml``'s value.
    """
    impl = FakeRetrieval(data_dir=tmp_path, top_k_final=2, rerank_top_n=20)
    registry.override("retrieval", impl)
    published(
        impl,
        make_doc("public", texts=[PUBLIC_TEXT] * 5, roles=PUBLIC_ROLES),
    )

    body = TestClient(build_app(lecteur_ctx)).post("/search", json={"query": QUERY}).json()

    assert len(body) == 2


def test_r4_the_context_comes_from_the_authentication_dependency(
    editeur_ctx: UserContext,
) -> None:
    """R4: the ``UserContext`` given to ``search`` is the one the dependency returned."""
    spy = SpyRetrieval()

    spy_client(editeur_ctx, spy).post("/search", json={"query": QUERY})

    _, seen_ctx, _ = spy.calls[0]
    assert seen_ctx is editeur_ctx
    assert seen_ctx.role == "editeur"


@pytest.mark.parametrize(
    "injected",
    [
        {"user_id": "00000000-0000-0000-0000-0000000000ff"},
        {"role": "admin"},
        {"allowed_roles": ["editeur"]},
        {"ctx": {"role": "editeur"}},
    ],
)
def test_r4_identity_fields_in_the_body_are_ignored(
    lecteur_ctx: UserContext, injected: dict[str, Any]
) -> None:
    """R4: nothing a client puts in the body can change who the search runs as.

    ``SearchRequest`` has no such field, so the value is dropped, and ``UserContext`` is frozen
    (00-shared §5.1). The context ``search`` receives stays the authenticated one.
    """
    spy = SpyRetrieval()

    response = spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY, **injected})

    assert response.status_code == 200
    _, seen_ctx, _ = spy.calls[0]
    assert seen_ctx is lecteur_ctx
    assert seen_ctx.role == "lecteur"
    assert set(SearchRequest.model_fields) == {"query", "top_k"}


# --- R5, R6, R7, R8: invalid input ------------------------------------------------------------


def test_r5_empty_query_is_422(client: TestClient) -> None:
    """R5: an empty query is ``InvalidInput`` (P2-11) and reaches the client as 422."""
    response = client.post("/search", json={"query": ""})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


@pytest.mark.parametrize(
    "query",
    [
        "   ",  # spaces only
        "\t\n ",  # whitespace only
        "ـــ",  # tatweel only: dropped by normalize_ar rule 4
        "؟؟؟ ...",  # punctuation only: rule 10 turns it into spaces
    ],
)
def test_r6_query_empty_after_normalisation_is_422(client: TestClient, query: str) -> None:
    """R6: a query that ``normalize_ar`` reduces to nothing is refused like an empty one."""
    response = client.post("/search", json={"query": query})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


@pytest.mark.parametrize("top_k", [0, -1, 21, 1000])
def test_r7_top_k_out_of_range_is_422(client: TestClient, top_k: int) -> None:
    """R7: ``top_k`` outside ``1 … rerank_top_n`` is 422 through ``InvalidInput``.

    ``rerank_top_n`` is 20 for ``FakeRetrieval``'s default, so 21 is already too large. The
    route adds no pydantic bound of its own: the check, and so the error format, stay the
    pipeline's (P2-11).
    """
    response = client.post("/search", json={"query": QUERY, "top_k": top_k})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


def test_r7_top_k_of_one_is_accepted(client: TestClient, fake_retrieval: FakeRetrieval) -> None:
    """The lower bound is inclusive: ``top_k = 1`` is valid, not an off-by-one 422."""
    published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT] * 3, roles=PUBLIC_ROLES))

    response = client.post("/search", json={"query": QUERY, "top_k": 1})

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_r8_missing_query_is_422(lecteur_ctx: UserContext) -> None:
    """R8: no ``query`` field at all is pydantic's own 422, and the pipeline is never called."""
    spy = SpyRetrieval()

    response = spy_client(lecteur_ctx, spy).post("/search", json={"top_k": 3})

    assert response.status_code == 422
    assert "detail" in response.json()  # FastAPI's validation shape, not AppError's
    assert spy.calls == []


def test_r8_wrong_type_for_top_k_is_422(lecteur_ctx: UserContext) -> None:
    """A ``top_k`` that is not an integer is refused before the pipeline sees it."""
    spy = SpyRetrieval()

    response = spy_client(lecteur_ctx, spy).post(
        "/search", json={"query": QUERY, "top_k": "beaucoup"}
    )

    assert response.status_code == 422
    assert spy.calls == []


# --- R11, R12: what comes back from the pipeline -----------------------------------------------


def test_r11_nothing_found_is_200_and_an_empty_list(
    client: TestClient, fake_retrieval: FakeRetrieval
) -> None:
    """R11: an empty result is a normal answer, not a 404 (P2-17)."""
    published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT], roles=PUBLIC_ROLES))

    response = client.post("/search", json={"query": NO_MATCH_QUERY})

    assert response.status_code == 200
    assert response.json() == []


def test_r11_an_empty_store_is_also_200_and_empty(client: TestClient) -> None:
    """Nothing indexed at all behaves the same way."""
    response = client.post("/search", json={"query": QUERY})

    assert response.status_code == 200
    assert response.json() == []


def test_r12_service_error_is_503_in_the_shared_format(lecteur_ctx: UserContext) -> None:
    """R12: ``ServiceError`` from the pipeline becomes 503 ``{"code": "service_error"}`` through
    the application's ``AppError`` handler (00-shared §7, P5-05). The route catches nothing."""
    spy = SpyRetrieval(error=ServiceError("qdrant unreachable"))

    response = spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY})

    assert response.status_code == 503
    assert response.json()["code"] == "service_error"


def test_r12_the_error_body_holds_no_query_text(lecteur_ctx: UserContext) -> None:
    """00-shared §7: an error message never carries the question."""
    spy = SpyRetrieval(error=ServiceError("qdrant unreachable"))

    response = spy_client(lecteur_ctx, spy).post("/search", json={"query": QUERY})

    assert QUERY not in response.text


# --- R13: the authenticated role decides what comes back ---------------------------------------


@pytest.fixture
def corpus(fake_retrieval: FakeRetrieval, lecteur_ctx: UserContext) -> FakeRetrieval:
    """A public document, an internal one, and a private upload owned by ``lecteur_ctx``."""
    published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT], roles=PUBLIC_ROLES))
    published(fake_retrieval, make_doc("internal", texts=[INTERNAL_TEXT], roles=INTERNAL_ROLES))
    published(
        fake_retrieval,
        make_doc("upload", texts=[PRIVATE_TEXT], roles=[], owner_id=lecteur_ctx.user_id),
    )
    return fake_retrieval


def titles_for(ctx: UserContext) -> set[str]:
    """The document titles a search through the route returns for this user."""
    response = TestClient(build_app(ctx)).post("/search", json={"query": QUERY, "top_k": 20})
    assert response.status_code == 200
    return {item["chunk"]["title"] for item in response.json()}


def test_r13_lecteur_sees_public_and_own_upload_but_not_the_internal_document(
    corpus: FakeRetrieval, lecteur_ctx: UserContext
) -> None:
    """R13: the visibility rule (00-shared §6.3) applies to the role the token carries."""
    assert titles_for(lecteur_ctx) == {"عنوان public", "عنوان upload"}


def test_r13_editeur_sees_public_and_internal_but_not_the_upload(
    corpus: FakeRetrieval, editeur_ctx: UserContext
) -> None:
    """The same question, a different role, a different answer."""
    assert titles_for(editeur_ctx) == {"عنوان public", "عنوان internal"}


def test_r13_another_lecteur_never_sees_the_private_upload(
    corpus: FakeRetrieval, other_lecteur_ctx: UserContext
) -> None:
    """A private upload belongs to its owner only (T4), whoever asks through the route."""
    assert titles_for(other_lecteur_ctx) == {"عنوان public"}


def test_r13_admin_sees_nothing_of_the_corpus(
    corpus: FakeRetrieval, admin_ctx: UserContext
) -> None:
    """``admin`` is not in any document's roles and owns nothing here (T3)."""
    assert titles_for(admin_ctx) == set()


def test_r13_the_internal_text_never_appears_in_a_lecteur_response(
    corpus: FakeRetrieval, lecteur_ctx: UserContext
) -> None:
    """Not the title, not the text, not a hint: the whole body is checked."""
    response = TestClient(build_app(lecteur_ctx)).post(
        "/search", json={"query": QUERY, "top_k": 20}
    )

    assert INTERNAL_TEXT not in response.text
    assert "عنوان internal" not in response.text


# --- R14: logs ---------------------------------------------------------------------------------


def test_r14_request_logs_hold_no_query_or_chunk_text(
    client: TestClient, fake_retrieval: FakeRetrieval, caplog: pytest.LogCaptureFixture
) -> None:
    """R14: nothing logged while serving the request carries the question or a chunk's text.

    Asserted over every record captured, message and ``extra`` fields alike (P2-29, T22). The
    route itself logs nothing; this is what proves it stays that way.
    """
    published(fake_retrieval, make_doc("public", texts=[PUBLIC_TEXT], roles=PUBLIC_ROLES))

    with caplog.at_level(logging.DEBUG):
        response = client.post("/search", json={"query": QUERY, "top_k": 3})
    assert response.status_code == 200 and response.json()  # the request really did find something

    blob = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    for secret in (QUERY, PUBLIC_TEXT, "عنوان public"):
        assert secret not in blob, secret


def test_r14_a_refused_request_logs_no_query_either(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The 422 path must not log the query as the reason for the refusal."""
    with caplog.at_level(logging.DEBUG):
        assert client.post("/search", json={"query": QUERY, "top_k": 999}).status_code == 422

    blob = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert QUERY not in blob


# --- Group 2: the real authentication dependency (R9, R10) -------------------------------------

LECTEUR_ROLE_ID = 3


@pytest.fixture
def auth_env() -> Iterator[SimpleNamespace]:
    """A SQLite database with one active and one inactive ``lecteur``, and a client that uses the
    real ``get_current_user_context``.

    Only ``get_db`` is overridden — the authentication dependency itself is the production one,
    so these tests exercise the bearer scheme, the JWT decoding and the database re-read of
    P5-19. The retrieval service is a recording double: what is under test is who the request
    runs as, not what the pipeline finds.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    session = session_factory()
    session.add(Role(id=LECTEUR_ROLE_ID, name="lecteur", web_enabled=False))
    session.flush()
    active_id, inactive_id = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            User(
                id=active_id,
                username="alice.lecteur",
                hashed_password=get_password_hash("StrongPass123!"),
                full_name="Alice Lecteur",
                role_id=LECTEUR_ROLE_ID,
                is_active=True,
            ),
            User(
                id=inactive_id,
                username="bob.disabled",
                hashed_password=get_password_hash("StrongPass123!"),
                full_name="Bob Disabled",
                role_id=LECTEUR_ROLE_ID,
                is_active=False,
            ),
        ]
    )
    session.commit()

    spy = SpyRetrieval([passage()])
    registry.override("retrieval", spy)

    app = FastAPI()
    app.include_router(router, prefix="/search")

    def _override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    @app.exception_handler(AppError)
    async def _app_error(_request: Any, exc: AppError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.http_status)

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, spy=spy, active_id=active_id, inactive_id=inactive_id)

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_r9_no_authorization_header_is_401(auth_env: SimpleNamespace) -> None:
    """R9: without a bearer token the request is ``Unauthenticated`` → 401, and the pipeline is
    never reached (``HTTPBearer`` is built with ``auto_error=False``, so P5 raises, not Starlette).
    """
    response = auth_env.client.post("/search", json={"query": QUERY})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert auth_env.spy.calls == []


@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-jwt",
        "Bearer ",
        "Basic YWxpY2U6c2VjcmV0",  # wrong scheme
    ],
)
def test_r10_an_unusable_token_is_401(auth_env: SimpleNamespace, header: str) -> None:
    """R10: a malformed token, an empty one or the wrong scheme are all 401."""
    response = auth_env.client.post(
        "/search", json={"query": QUERY}, headers={"Authorization": header}
    )

    assert response.status_code == 401
    assert auth_env.spy.calls == []


def test_r10_an_expired_token_is_401(auth_env: SimpleNamespace) -> None:
    """R10: a token that was valid but has expired no longer opens the route."""
    expired = create_access_token(
        {"sub": str(auth_env.active_id)}, expires_delta=timedelta(minutes=-5)
    )

    response = auth_env.client.post(
        "/search", json={"query": QUERY}, headers={"Authorization": f"Bearer {expired}"}
    )

    assert response.status_code == 401
    assert auth_env.spy.calls == []


def test_r10_a_token_for_an_unknown_user_is_401(auth_env: SimpleNamespace) -> None:
    """A correctly signed token whose subject is not in the database is refused (P5-19: the user
    is re-read on every request, the token is not trusted on its own)."""
    orphan = create_access_token({"sub": str(uuid.uuid4())})

    response = auth_env.client.post(
        "/search", json={"query": QUERY}, headers={"Authorization": f"Bearer {orphan}"}
    )

    assert response.status_code == 401
    assert auth_env.spy.calls == []


def test_r10_a_token_for_a_deactivated_user_is_401(auth_env: SimpleNamespace) -> None:
    """A disabled account loses access immediately, without waiting for its token to expire."""
    token = create_access_token({"sub": str(auth_env.inactive_id)})

    response = auth_env.client.post(
        "/search", json={"query": QUERY}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert auth_env.spy.calls == []


def test_a_valid_token_reaches_the_pipeline_with_the_database_role(
    auth_env: SimpleNamespace,
) -> None:
    """The positive half of R9/R10: a real token opens the route, and the context handed to
    ``search`` is built from the database — the role is the one stored, not one the client chose.
    """
    token = create_access_token({"sub": str(auth_env.active_id)})

    response = auth_env.client.post(
        "/search",
        json={"query": QUERY, "top_k": 4, "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    query, ctx, top_k = auth_env.spy.calls[0]
    assert (query, top_k) == (QUERY, 4)
    assert ctx.user_id == auth_env.active_id
    assert ctx.username == "alice.lecteur"
    assert ctx.role == "lecteur"  # not the "admin" the body asked for
    assert ctx.web_enabled is False


# --- Group 3: the route in the real application ------------------------------------------------


def test_route_is_mounted_in_the_application() -> None:
    """00-shared §8: the application serves ``POST /search``.

    Read from the OpenAPI schema, which is the application's public contract — recent FastAPI
    versions keep an included router wrapped in ``app.routes`` instead of flattening it, so the
    schema is both the stabler and the more meaningful place to ask.

    ``src/api/main.py`` is P5's file and P2 does not touch it; this test is what says the route
    stays reachable where the specification puts it.
    """
    from src.api.main import app

    paths = app.openapi()["paths"]

    assert "post" in paths["/search"]
    assert "post" in paths["/search/"]


def test_the_real_application_refuses_an_unauthenticated_search() -> None:
    """The whole P5 stack, not a local app: middleware, real dependency, real error handler.

    No ``dependency_overrides`` at all here, and no database is reached — the bearer scheme finds
    no token and ``Unauthenticated`` is raised before the session is ever queried. What this adds
    to R9 is that ``src/api/main.py``'s own handler produces the body, and that its request-id
    middleware (P5-02) wrapped the call.
    """
    from src.api.main import app

    with_client = TestClient(app, raise_server_exceptions=False)
    response = with_client.post("/search", json={"query": QUERY})

    assert response.status_code == 401
    assert response.json() == {"code": "unauthenticated", "message": "invalid token"}
    assert response.headers["X-Request-ID"]


def test_the_route_and_p3s_graph_share_one_retrieval(fake_retrieval: FakeRetrieval) -> None:
    """The API and P3's graph consume the *same* ``Retrieval``, not two pipelines.

    ``src/agents/orchestrator/graph.py:search_node`` calls ``get_retrieval().search(query, ctx,
    top_k=...)``; the route calls ``get_retrieval().search(body.query, ctx, body.top_k)``. Both
    go through P5's registry, which keeps one instance per process, so whatever
    ``contracts.retrieval`` selects is what both of them get. P3's file is imported here and
    never touched.
    """
    from src.agents.orchestrator.graph import get_retrieval as graph_get_retrieval
    from src.api.routes.search import get_retrieval as route_get_retrieval

    assert route_get_retrieval is graph_get_retrieval
    assert route_get_retrieval() is graph_get_retrieval() is fake_retrieval


def test_the_route_calls_the_shared_search_signature() -> None:
    """The route's call matches ``Retrieval.search`` (00-shared §6.3) for both implementations."""
    import inspect

    from src.core.contracts import Retrieval
    from src.retrieval.search import Retrieval as RealRetrieval

    expected = inspect.signature(Retrieval.search)
    assert inspect.signature(FakeRetrieval.search) == expected
    assert inspect.signature(RealRetrieval.search) == expected


def test_the_route_handler_is_synchronous() -> None:
    """``search`` must stay a plain ``def`` so FastAPI runs it in a worker thread.

    ``Retrieval.search`` blocks on Qdrant and on P6's models service. As an ``async def`` it would
    hold the event loop for that whole time and stall every other request, ``/health`` and
    ``/ask``'s stream included.
    """
    import inspect

    from src.api.routes.search import search as handler

    assert not inspect.iscoroutinefunction(handler)
