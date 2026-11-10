"""Contract tests for the ``Retrieval`` Protocol (00-shared §6.3, §9; P2 spec §8).

Cases T1–T8, T10 and T12 of P2-retrieval.md §8, each parametrized over both implementations:
``FakeRetrieval`` and the real one. T9 and T11 are P2's own tests, not contract tests.

Every test talks to the Protocol only — ``index``, ``search``, ``update_roles``, ``hide``,
``show``, ``delete`` — so the same assertions hold for a JSONL file and for Qdrant. What is
visible is therefore read back through ``search``, the contract's only read path.
"""

import importlib
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from src.core.contracts import (
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    Chunk,
    InvalidInput,
    Retrieval,
    UserContext,
    make_chunk_id,
    make_doc_id,
)
from src.core.contracts.fakes.retrieval import FakeRetrieval
from src.ingestion.normalize import normalize_ar

# --- Local fixtures ---------------------------------------------------------------------------
# TEMPORARY: `sample_chunks` (P1) and `lecteur_ctx`, `editeur_ctx`, `admin_ctx`,
# `other_lecteur_ctx` (P5) are not merged yet — there is no tests/conftest.py and no
# tests/fixtures/sample_chunks.jsonl. The chunks and contexts below stand in for them and should
# be deleted in favour of the shared fixtures as soon as those land (P2-C-fatima.md, 00-shared §9).

LECTEUR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_LECTEUR_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
EDITEUR_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
ADMIN_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")

PUBLIC_DOC_ID = make_doc_id(b"public-doc", None)
INTERNAL_DOC_ID = make_doc_id(b"internal-doc", None)
PRIVATE_DOC_ID = make_doc_id(b"private-doc", LECTEUR_ID)
UNSHOWN_DOC_ID = make_doc_id(b"unshown-doc", None)
DELETED_DOC_ID = make_doc_id(b"deleted-doc", None)
RESIZED_DOC_ID = make_doc_id(b"resized-doc", None)

ALL_DOC_IDS = (
    PUBLIC_DOC_ID,
    INTERNAL_DOC_ID,
    PRIVATE_DOC_ID,
    UNSHOWN_DOC_ID,
    DELETED_DOC_ID,
    RESIZED_DOC_ID,
)

# Every document below contains "المادة", so BROAD_QUERY reaches all of them and a visibility test
# can assert on exactly which documents come back.
BROAD_QUERY = "المادة"
PRIVATE_TEXT = "المادة 5 من الوثيقة الخاصة"
UNSHOWN_TEXT = "المادة 6 من الوثيقة المخفية"
DELETED_TEXT = "المادة 7 من الوثيقة المحذوفة"

# top_k must stay within 1 … retrieval.rerank_top_n (20) and above the number of chunks indexed
# here, so a visibility assertion is never truncated by the limit.
TOP_K = 20


def _chunks(
    doc_id: str,
    texts: list[str],
    *,
    title: str,
    roles: list[str] | None = None,
    owner_id: uuid.UUID | None = None,
) -> list[Chunk]:
    """All chunks of one document, numbered 0 … len(texts) - 1."""
    return [
        Chunk(
            chunk_id=make_chunk_id(doc_id, i),
            doc_id=doc_id,
            chunk_index=i,
            total_chunks=len(texts),
            text=text,
            text_normalized=normalize_ar(text),
            title=title,
            article=None,
            hierarchy=[],
            page_start=1,
            page_end=1,
            language="ar",
            source_file="doc.pdf",
            source=None,
            date=None,
            allowed_roles=list(roles or []),
            owner_id=owner_id,
        )
        for i, text in enumerate(texts)
    ]


def _ctx(role: str, user_id: uuid.UUID) -> UserContext:
    return UserContext(
        user_id=user_id,
        username=f"user-{role}",
        role=role,
        web_enabled=False,
        request_id=uuid.uuid4(),
    )


@pytest.fixture
def lecteur_ctx() -> UserContext:
    return _ctx("lecteur", LECTEUR_ID)


@pytest.fixture
def other_lecteur_ctx() -> UserContext:
    return _ctx("lecteur", OTHER_LECTEUR_ID)


@pytest.fixture
def editeur_ctx() -> UserContext:
    return _ctx("editeur", EDITEUR_ID)


@pytest.fixture
def admin_ctx() -> UserContext:
    return _ctx("admin", ADMIN_ID)


# --- The two implementations -----------------------------------------------------------------

# Looked up by name, not imported, because whether it exists is a runtime question today.
REAL_FACTORY = "real_retrieval"  # src/retrieval/__init__.py:real_retrieval() (00-shared §9)


def _real_retrieval() -> Retrieval:
    """The real implementation, or a skip while it cannot be used.

    Imported here and not at module level, through ``importlib`` so a missing name is not a static
    error: ``src.retrieval.store`` imports ``qdrant_client`` when the module is loaded, and this
    file must still collect — and run its fake half — without that package installed.
    """
    try:
        module = importlib.import_module("src.retrieval")
    except ImportError as exc:  # qdrant_client or another dependency is missing
        pytest.skip(f"real retrieval dependencies unavailable ({type(exc).__name__})")
    factory: Callable[[], Retrieval] | None = getattr(module, REAL_FACTORY, None)
    if factory is None:
        pytest.skip(f"{REAL_FACTORY}() does not exist yet")
    try:
        # real_retrieval() creates the collection on its first call, so this needs Qdrant.
        return factory()
    except Exception as exc:  # Qdrant unreachable, bad config…
        pytest.skip(f"real retrieval unusable ({type(exc).__name__})")


@pytest.fixture(params=["fake", "real"])
def retrieval(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Retrieval]:
    """One ``Retrieval`` implementation, with storage of its own.

    The fake writes to ``tmp_path/chunks.jsonl``, so each test starts from an empty store and the
    project's ``data/processed`` is never touched. The real one shares its Qdrant collection, so
    the documents this module uses are deleted afterwards instead.
    """
    if request.param == "fake":
        yield FakeRetrieval(data_dir=tmp_path)
        return
    impl = _real_retrieval()
    for doc_id in ALL_DOC_IDS:  # leftovers from an interrupted run
        impl.delete(doc_id)
    yield impl
    for doc_id in ALL_DOC_IDS:
        impl.delete(doc_id)


@pytest.fixture
def corpus(retrieval: Retrieval) -> Retrieval:
    """A public, an internal and a private document, all indexed and shown.

    Mirrors the shape of the `sample_chunks` fixture T1–T4 expect: public (``["lecteur",
    "editeur"]``), internal (``["editeur"]``) and a private upload of `lecteur_ctx`'s user.
    """
    documents = [
        _chunks(
            PUBLIC_DOC_ID,
            ["المادة 1 من قانون النشر", "المادة 2 من قانون النشر"],
            title="قانون النشر",
            roles=PUBLIC_ROLES,
        ),
        _chunks(
            INTERNAL_DOC_ID,
            ["المادة 3 من المذكرة الداخلية", "المادة 4 من المذكرة الداخلية"],
            title="المذكرة الداخلية",
            roles=INTERNAL_ROLES,
        ),
        _chunks(
            PRIVATE_DOC_ID,
            [PRIVATE_TEXT],
            title="الوثيقة الخاصة",
            roles=[],  # a private upload has no roles; owner_id carries the access
            owner_id=LECTEUR_ID,
        ),
    ]
    for chunks in documents:
        retrieval.index(chunks)
        retrieval.show(chunks[0].doc_id)  # index stores chunks hidden (P2-06)
    return retrieval


def _doc_ids(retrieval: Retrieval, query: str, ctx: UserContext) -> set[str]:
    """The documents a search returns, which is what the visibility rule is about."""
    return {p.chunk.doc_id for p in retrieval.search(query, ctx, TOP_K)}


# --- T1–T8, T10, T12 -------------------------------------------------------------------------


def test_t1_lecteur_sees_public_documents_and_own_uploads(
    corpus: Retrieval, lecteur_ctx: UserContext
) -> None:
    """T1: only chunks whose allowed_roles contains lecteur, or owned by that user."""
    assert _doc_ids(corpus, BROAD_QUERY, lecteur_ctx) == {PUBLIC_DOC_ID, PRIVATE_DOC_ID}


def test_t2_editeur_sees_public_and_internal_but_no_private_upload(
    corpus: Retrieval, editeur_ctx: UserContext
) -> None:
    """T2: public + internal chunks, and no one else's private upload."""
    assert _doc_ids(corpus, BROAD_QUERY, editeur_ctx) == {PUBLIC_DOC_ID, INTERNAL_DOC_ID}


def test_t3_admin_sees_only_own_uploads(corpus: Retrieval, admin_ctx: UserContext) -> None:
    """T3: only the admin's own uploads — there are none here, so the result is empty."""
    assert corpus.search(BROAD_QUERY, admin_ctx, TOP_K) == []


def test_t4_private_upload_is_never_returned_to_another_user(
    corpus: Retrieval, other_lecteur_ctx: UserContext
) -> None:
    """T4: another lecteur searching the upload's exact words never gets it."""
    assert PRIVATE_DOC_ID not in _doc_ids(corpus, PRIVATE_TEXT, other_lecteur_ctx)


@pytest.mark.parametrize(
    "role, user_id", [("lecteur", LECTEUR_ID), ("editeur", EDITEUR_ID), ("admin", ADMIN_ID)]
)
def test_t5_document_never_shown_is_not_returned(
    retrieval: Retrieval, role: str, user_id: uuid.UUID
) -> None:
    """T5: a document indexed but never shown is invisible to every role."""
    retrieval.index(
        _chunks(UNSHOWN_DOC_ID, [UNSHOWN_TEXT], title="الوثيقة المخفية", roles=PUBLIC_ROLES)
    )
    assert retrieval.search(UNSHOWN_TEXT, _ctx(role, user_id), TOP_K) == []


def test_t6_hide_removes_the_document_and_show_brings_it_back(
    corpus: Retrieval, lecteur_ctx: UserContext
) -> None:
    """T6: hide -> not returned; show -> returned again."""
    assert PUBLIC_DOC_ID in _doc_ids(corpus, BROAD_QUERY, lecteur_ctx)
    corpus.hide(PUBLIC_DOC_ID)
    assert PUBLIC_DOC_ID not in _doc_ids(corpus, BROAD_QUERY, lecteur_ctx)
    corpus.show(PUBLIC_DOC_ID)
    assert PUBLIC_DOC_ID in _doc_ids(corpus, BROAD_QUERY, lecteur_ctx)


def test_t7_update_roles_opens_an_internal_document_to_lecteur(
    corpus: Retrieval, lecteur_ctx: UserContext
) -> None:
    """T7: an internal document given ["lecteur", "editeur"] is then returned for lecteur."""
    assert INTERNAL_DOC_ID not in _doc_ids(corpus, BROAD_QUERY, lecteur_ctx)
    corpus.update_roles(INTERNAL_DOC_ID, PUBLIC_ROLES)
    assert INTERNAL_DOC_ID in _doc_ids(corpus, BROAD_QUERY, lecteur_ctx)


def test_t8_delete_twice_is_not_an_error_and_leaves_nothing(
    retrieval: Retrieval, editeur_ctx: UserContext
) -> None:
    """T8: deleting twice raises nothing and no chunk of that doc_id is left."""
    retrieval.index(
        _chunks(DELETED_DOC_ID, [DELETED_TEXT], title="الوثيقة المحذوفة", roles=PUBLIC_ROLES)
    )
    retrieval.show(DELETED_DOC_ID)
    assert DELETED_DOC_ID in _doc_ids(retrieval, DELETED_TEXT, editeur_ctx)
    retrieval.delete(DELETED_DOC_ID)
    retrieval.delete(DELETED_DOC_ID)  # idempotent
    assert DELETED_DOC_ID not in _doc_ids(retrieval, DELETED_TEXT, editeur_ctx)


def test_t10_reindexing_shorter_drops_the_leftover_chunks(
    retrieval: Retrieval, editeur_ctx: UserContext
) -> None:
    """T10: a 5-chunk document re-indexed with 3 chunks keeps exactly chunks 0–2."""
    texts = [f"المادة {i} من الوثيقة المتغيرة" for i in range(5)]
    retrieval.index(_chunks(RESIZED_DOC_ID, texts, title="الوثيقة المتغيرة", roles=PUBLIC_ROLES))
    retrieval.index(
        _chunks(RESIZED_DOC_ID, texts[:3], title="الوثيقة المتغيرة", roles=PUBLIC_ROLES)
    )
    retrieval.show(RESIZED_DOC_ID)  # re-indexing stores the chunks hidden again
    passages = retrieval.search("الوثيقة المتغيرة", editeur_ctx, TOP_K)
    assert {p.chunk.chunk_index for p in passages if p.chunk.doc_id == RESIZED_DOC_ID} == {0, 1, 2}


def test_t12_search_without_a_context_is_invalid_input(retrieval: Retrieval) -> None:
    """T12: search(query, None) raises InvalidInput."""
    with pytest.raises(InvalidInput):
        retrieval.search(BROAD_QUERY, None, TOP_K)  # type: ignore[arg-type]
