"""Access tests on the real pipeline: ``Retrieval`` over ``QdrantStore`` and ``BM25Index``
(P2 spec §8: T1, T2, T3, T4, T13; 00-shared §6.3).

Every test goes through ``Retrieval.search``, the only way the rest of the system reaches P2, with
P1's ``sample_chunks`` and P5's fixed user contexts. The expected sets are computed from the
visibility rule written out again in ``visible_ids``, independently of the code under test.

With the hash embeddings of ``p2_helpers``, the vector half returns every chunk the user may see
(up to ``top_k_vector``), so a search with ``top_k = rerank_top_n`` must return **exactly** the
visible set: a missing chunk or an extra one both fail.

The "not counted in the search log line" part of T13 is checked once the P2-29 log line exists.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from p2_helpers import HashModels, make_doc
from qdrant_client import QdrantClient

from src.core.contracts import PUBLIC_ROLES, Chunk, UserContext
from src.retrieval.bm25 import BM25Index
from src.retrieval.search import DEFAULT_RERANK_TOP_N, Retrieval
from src.retrieval.store import QdrantStore
from src.retrieval.tokenizer import tokenize
from src.retrieval.version import bump_version

ROLES = ["lecteur_ctx", "other_lecteur_ctx", "editeur_ctx", "admin_ctx"]


def visible_ids(chunks: list[Chunk], ctx: UserContext) -> set[str]:
    """The visibility rule of 00-shared §6.3 (every chunk here is shown)."""
    return {c.chunk_id for c in chunks if c.owner_id == ctx.user_id or ctx.role in c.allowed_roles}


class Searcher:
    """The real store, BM25 index and pipeline, wired as ``real_retrieval()`` wires them."""

    def __init__(self, qdrant: QdrantClient, collection: str, version_file: Path) -> None:
        self.store = QdrantStore(
            qdrant, HashModels(), collection=collection, on_write=lambda: bump_version(version_file)
        )
        self.store.ensure_collection()
        self.bm25 = BM25Index(load_payloads=self.store.scroll_payloads, version_file=version_file)
        self.retrieval = Retrieval(self.store, self.bm25)

    def publish(self, chunks: list[Chunk]) -> None:
        """Indexes every document of ``chunks`` and shows it (``index`` stores it hidden)."""
        docs: dict[str, list[Chunk]] = {}
        for c in chunks:
            docs.setdefault(c.doc_id, []).append(c)
        for doc in docs.values():
            self.store.index(sorted(doc, key=lambda c: c.chunk_index))
            self.store.show(doc[0].doc_id)

    def returned(self, query: str, ctx: UserContext) -> set[str]:
        passages = self.retrieval.search(query, ctx, DEFAULT_RERANK_TOP_N)
        return {p.chunk.chunk_id for p in passages}

    def bm25_ids(self, chunk: Chunk, ctx: UserContext) -> set[str]:
        return set(self.bm25.search(tokenize(chunk.text_normalized), ctx, 30))


@pytest.fixture
def searcher(qdrant: QdrantClient, collection: str, tmp_path: Path) -> Iterator[Searcher]:
    yield Searcher(qdrant, collection, tmp_path / "indexes" / "retrieval.version")


@pytest.fixture
def published(searcher: Searcher, sample_chunks: list[Chunk], editeur_ctx: UserContext) -> Searcher:
    # The exact-set checks need every visible chunk to fit in one result. The editeur sees the
    # most chunks of any role in the fixtures.
    assert len(visible_ids(sample_chunks, editeur_ctx)) <= DEFAULT_RERANK_TOP_N
    searcher.publish(sample_chunks)
    return searcher


def by_owner(chunks: list[Chunk], ctx: UserContext) -> list[Chunk]:
    return [c for c in chunks if c.owner_id == ctx.user_id]


def restricted_for(chunks: list[Chunk], ctx: UserContext) -> list[Chunk]:
    allowed = visible_ids(chunks, ctx)
    return [c for c in chunks if c.chunk_id not in allowed]


# --- The fixtures cover every case the tests below rely on ----------------------------------


def test_sample_chunks_cover_every_access_case(
    sample_chunks: list[Chunk], lecteur_ctx: UserContext, other_lecteur_ctx: UserContext
) -> None:
    assert any(c.allowed_roles == ["editeur"] for c in sample_chunks)  # internal
    assert any(set(c.allowed_roles) == set(PUBLIC_ROLES) for c in sample_chunks)  # public
    assert by_owner(sample_chunks, lecteur_ctx)  # a private upload of lecteur_ctx's user
    assert by_owner(sample_chunks, other_lecteur_ctx)  # and one of another lecteur


# --- T1, T2, T3: each role sees exactly what it may see -------------------------------------


@pytest.mark.parametrize("ctx_name", ROLES)
def test_t1_t3_every_query_returns_exactly_the_visible_chunks(
    published: Searcher,
    sample_chunks: list[Chunk],
    ctx_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """T1 (lecteur), T2 (editeur), T3 (admin): whatever the query, the result is the visible set,
    and BM25 never even offers a chunk outside it."""
    ctx: UserContext = request.getfixturevalue(ctx_name)
    allowed = visible_ids(sample_chunks, ctx)
    for chunk in sample_chunks:
        assert published.returned(chunk.text, ctx) == allowed
        assert published.bm25_ids(chunk, ctx) <= allowed


def test_t1_lecteur_sees_public_and_own_uploads_only(
    published: Searcher, sample_chunks: list[Chunk], lecteur_ctx: UserContext
) -> None:
    returned = published.returned(sample_chunks[0].text, lecteur_ctx)
    for c in sample_chunks:
        expected = "lecteur" in c.allowed_roles or c.owner_id == lecteur_ctx.user_id
        assert (c.chunk_id in returned) is expected


def test_t2_editeur_sees_public_and_internal_but_no_upload(
    published: Searcher, sample_chunks: list[Chunk], editeur_ctx: UserContext
) -> None:
    returned = published.returned(sample_chunks[0].text, editeur_ctx)
    for c in sample_chunks:
        assert (c.chunk_id in returned) is (c.owner_id is None)


def test_t3_admin_sees_nothing_from_the_fixtures(
    published: Searcher, sample_chunks: list[Chunk], admin_ctx: UserContext
) -> None:
    for c in sample_chunks:
        assert published.returned(c.text, admin_ctx) == set()


def test_t3_admin_sees_only_their_own_upload(
    published: Searcher, sample_chunks: list[Chunk], admin_ctx: UserContext
) -> None:
    upload = make_doc("admin-upload", roles=[], owner_id=admin_ctx.user_id)
    published.publish(upload)

    returned = published.returned(upload[0].text, admin_ctx)

    assert returned == {c.chunk_id for c in upload}


# --- T4: a private upload never reaches another user ---------------------------------------


@pytest.mark.parametrize(
    "owner_name,other_name",
    [("lecteur_ctx", "other_lecteur_ctx"), ("other_lecteur_ctx", "lecteur_ctx")],
)
def test_t4_private_upload_never_returned_to_another_lecteur(
    published: Searcher,
    sample_chunks: list[Chunk],
    owner_name: str,
    other_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """T4, both ways: the upload's exact words find it for its owner and never for the other."""
    owner: UserContext = request.getfixturevalue(owner_name)
    other: UserContext = request.getfixturevalue(other_name)
    for upload in by_owner(sample_chunks, owner):
        assert upload.chunk_id in published.returned(upload.text, owner)
        assert upload.chunk_id not in published.returned(upload.text, other)
        assert upload.chunk_id not in published.bm25_ids(upload, other)


@pytest.mark.parametrize("ctx_name", ["editeur_ctx", "admin_ctx"])
def test_t4_no_other_role_sees_a_private_upload(
    published: Searcher,
    sample_chunks: list[Chunk],
    lecteur_ctx: UserContext,
    ctx_name: str,
    request: pytest.FixtureRequest,
) -> None:
    ctx: UserContext = request.getfixturevalue(ctx_name)
    for upload in by_owner(sample_chunks, lecteur_ctx):
        assert upload.chunk_id not in published.returned(upload.text, ctx)


# --- T13: a restricted chunk's own text as the query ----------------------------------------


@pytest.mark.parametrize("ctx_name", ROLES)
def test_t13_restricted_chunk_not_returned_on_its_exact_text(
    published: Searcher,
    sample_chunks: list[Chunk],
    ctx_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """T13: for every role, each chunk it may not see, searched word for word, stays out of the
    result and out of BM25's candidates."""
    ctx: UserContext = request.getfixturevalue(ctx_name)
    restricted = restricted_for(sample_chunks, ctx)
    assert restricted  # every role has something it may not see in the fixtures
    for chunk in restricted:
        assert chunk.chunk_id not in published.returned(chunk.text, ctx)
        assert chunk.chunk_id not in published.bm25_ids(chunk, ctx)
