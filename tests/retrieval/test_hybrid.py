"""The real hybrid pipeline: ``Retrieval`` on the real ``QdrantStore`` and the real ``BM25Index``
(P2 spec P2-13, P2-14, §6.5, T15).

``test_search.py`` checks the pipeline with a BM25 double; this file wires in the real index and
checks the two layers of protection together:

1. the version file normally keeps BM25 up to date (``on_write`` = ``bump_version``);
2. when BM25 is behind Qdrant anyway, the Qdrant re-check (P2-14) still drops what the user may
   not see (T15).

Every T15 test first proves that BM25 really is stale (it still offers the chunk), then that the
final result does not contain it: otherwise the test could pass without the re-check doing
anything.

Every corpus includes public "filler" chunks without the query words: on a tiny corpus where
every chunk has them, BM25Okapi gives negative scores and returns nothing.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from p2_helpers import HashModels, make_ctx, make_doc
from qdrant_client import QdrantClient

from src.core.contracts import INTERNAL_ROLES, PUBLIC_ROLES, Chunk, UserContext
from src.ingestion import normalize_ar
from src.retrieval.bm25 import BM25Index
from src.retrieval.search import Retrieval
from src.retrieval.store import QdrantStore
from src.retrieval.tokenizer import tokenize
from src.retrieval.version import bump_version, read_version

QUERY = "معالجة الطلبات"
TOKENS = tokenize(normalize_ar(QUERY))
MATCH_TEXT = normalize_ar("يتعين على المصالح معالجة الطلبات في أجل ثلاثين يوما")


class Pipeline:
    """The three real objects, wired as ``real_retrieval()`` will wire them."""

    def __init__(
        self,
        qdrant: QdrantClient,
        collection: str,
        on_write: Callable[[], None],
        version_file: Path,
    ) -> None:
        self.qdrant = qdrant
        self.version_file = version_file
        self.store = QdrantStore(qdrant, HashModels(), collection=collection, on_write=on_write)
        self.store.ensure_collection()
        self.bm25 = BM25Index(load_payloads=self.store.scroll_payloads, version_file=version_file)
        self.retrieval = Retrieval(self.store, self.bm25)

    def shown(self, chunks: list[Chunk]) -> list[Chunk]:
        """Indexes a document and makes it searchable (``index`` stores it hidden)."""
        self.store.index(chunks)
        self.store.show(chunks[0].doc_id)
        return chunks

    def add_filler(self, n: int = 10) -> None:
        for i in range(n):
            self.shown(make_doc(f"filler-{i}", texts=[f"موضوع مختلف رقم {i}"], roles=PUBLIC_ROLES))

    def bm25_ids(self, ctx: UserContext) -> list[str]:
        return self.bm25.search(TOKENS, ctx, 30)

    def returned(self, ctx: UserContext, query: str = QUERY) -> set[str]:
        return {p.chunk.chunk_id for p in self.retrieval.search(query, ctx, 20)}


@pytest.fixture
def version_file(tmp_path: Path) -> Path:
    return tmp_path / "indexes" / "retrieval.version"


@pytest.fixture
def pipeline(qdrant: QdrantClient, collection: str, version_file: Path) -> Pipeline:
    """Normal wiring: every write through the store bumps the version."""
    return Pipeline(qdrant, collection, lambda: bump_version(version_file), version_file)


@pytest.fixture
def silent_pipeline(qdrant: QdrantClient, collection: str, version_file: Path) -> Pipeline:
    """Broken on purpose: writes through the store never bump the version, so BM25 goes stale."""
    return Pipeline(qdrant, collection, lambda: None, version_file)


def target_doc(name: str = "target", roles: list[str] | None = None) -> list[Chunk]:
    return make_doc(name, texts=[MATCH_TEXT], roles=roles or PUBLIC_ROLES)


# --- T15: stale BM25, caught by the Qdrant re-check (P2-14) ------------------------------------


def test_t15_hidden_by_direct_write_without_bump_is_not_returned(
    pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    """T15: a document hidden in Qdrant with no version bump is still offered by BM25, but the
    re-check drops it."""
    target = pipeline.shown(target_doc())[0].chunk_id
    pipeline.add_filler()
    assert target in pipeline.returned(lecteur_ctx)  # BM25 is built and sees it

    version = read_version(pipeline.version_file)
    pipeline.qdrant.set_payload(
        pipeline.store.collection, payload={"hidden": True}, points=[target]
    )
    assert read_version(pipeline.version_file) == version  # no bump: BM25 stays stale

    assert target in pipeline.bm25_ids(lecteur_ctx)  # BM25 really is behind Qdrant
    assert target not in pipeline.returned(lecteur_ctx)  # the re-check caught it


def test_t15_hide_through_a_store_that_does_not_bump(
    silent_pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    """T15 on the real ``hide`` path, with the version bump missing."""
    p = silent_pipeline
    chunks = p.shown(target_doc())
    p.add_filler()
    bump_version(p.version_file)  # one bump so BM25 is built with the document visible
    assert chunks[0].chunk_id in p.returned(lecteur_ctx)

    p.store.hide(chunks[0].doc_id)  # on_write does nothing

    assert chunks[0].chunk_id in p.bm25_ids(lecteur_ctx)
    assert chunks[0].chunk_id not in p.returned(lecteur_ctx)


def test_t15_roles_restricted_without_bump_are_not_returned(
    silent_pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    """Same protection when a public document becomes internal and BM25 still has old roles."""
    p = silent_pipeline
    chunks = p.shown(target_doc())
    p.add_filler()
    bump_version(p.version_file)
    assert chunks[0].chunk_id in p.returned(lecteur_ctx)

    p.store.update_roles(chunks[0].doc_id, INTERNAL_ROLES)  # on_write does nothing

    assert chunks[0].chunk_id in p.bm25_ids(lecteur_ctx)
    assert chunks[0].chunk_id not in p.returned(lecteur_ctx)


def test_t15_deleted_document_is_not_returned(
    silent_pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    """A deleted document still in a stale BM25 cannot come back: Qdrant no longer has it."""
    p = silent_pipeline
    chunks = p.shown(target_doc())
    p.add_filler()
    bump_version(p.version_file)
    assert chunks[0].chunk_id in p.returned(lecteur_ctx)

    p.store.delete(chunks[0].doc_id)  # on_write does nothing

    assert chunks[0].chunk_id in p.bm25_ids(lecteur_ctx)
    assert chunks[0].chunk_id not in p.returned(lecteur_ctx)


# --- Normal wiring: the version file keeps BM25 up to date (§6.5) ------------------------------


def test_hide_bumps_the_version_and_bm25_drops_the_chunk(
    pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    chunks = pipeline.shown(target_doc())
    pipeline.add_filler()
    assert chunks[0].chunk_id in pipeline.returned(lecteur_ctx)

    pipeline.store.hide(chunks[0].doc_id)

    assert chunks[0].chunk_id not in pipeline.bm25_ids(lecteur_ctx)  # rebuilt, not just rechecked
    assert chunks[0].chunk_id not in pipeline.returned(lecteur_ctx)


def test_show_again_makes_the_chunk_come_back(pipeline: Pipeline, lecteur_ctx: UserContext) -> None:
    chunks = pipeline.shown(target_doc())
    pipeline.add_filler()
    pipeline.store.hide(chunks[0].doc_id)
    assert chunks[0].chunk_id not in pipeline.returned(lecteur_ctx)

    pipeline.store.show(chunks[0].doc_id)

    assert chunks[0].chunk_id in pipeline.bm25_ids(lecteur_ctx)
    assert chunks[0].chunk_id in pipeline.returned(lecteur_ctx)


def test_new_document_is_found_by_bm25_once_shown(
    pipeline: Pipeline, lecteur_ctx: UserContext
) -> None:
    pipeline.add_filler()
    assert pipeline.bm25_ids(lecteur_ctx) == []  # BM25 built without the document

    chunks = target_doc("late")
    pipeline.store.index(chunks)
    assert pipeline.bm25_ids(lecteur_ctx) == []  # indexed hidden (P2-08)

    pipeline.store.show(chunks[0].doc_id)
    assert pipeline.bm25_ids(lecteur_ctx) == [chunks[0].chunk_id]
    assert chunks[0].chunk_id in pipeline.returned(lecteur_ctx)


# --- Visibility end to end, with P1's sample chunks and P5's contexts ---------------------------


def visible_ids(chunks: list[Chunk], ctx: UserContext) -> set[str]:
    """The visibility rule of 00-shared §6.3, written out independently of the code under test."""
    return {c.chunk_id for c in chunks if c.owner_id == ctx.user_id or ctx.role in c.allowed_roles}


@pytest.mark.parametrize(
    "ctx_name", ["lecteur_ctx", "other_lecteur_ctx", "editeur_ctx", "admin_ctx"]
)
def test_sample_chunks_only_visible_chunks_are_returned(
    pipeline: Pipeline,
    sample_chunks: list[Chunk],
    ctx_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """For each role, every query built from a chunk's own words returns only visible chunks,
    and BM25 never offers a forbidden one either (the re-check is not what protects here)."""
    ctx: UserContext = request.getfixturevalue(ctx_name)
    docs: dict[str, list[Chunk]] = {}
    for c in sample_chunks:
        docs.setdefault(c.doc_id, []).append(c)
    for chunks in docs.values():
        pipeline.shown(sorted(chunks, key=lambda c: c.chunk_index))

    allowed = visible_ids(sample_chunks, ctx)
    for c in sample_chunks:
        tokens = tokenize(c.text_normalized)
        assert set(pipeline.bm25.search(tokens, ctx, 30)) <= allowed
        assert pipeline.returned(ctx, c.text) <= allowed


def test_sample_chunks_private_upload_found_by_its_owner_only(
    pipeline: Pipeline,
    sample_chunks: list[Chunk],
    lecteur_ctx: UserContext,
    other_lecteur_ctx: UserContext,
) -> None:
    docs: dict[str, list[Chunk]] = {}
    for c in sample_chunks:
        docs.setdefault(c.doc_id, []).append(c)
    for chunks in docs.values():
        pipeline.shown(sorted(chunks, key=lambda c: c.chunk_index))

    private = next(c for c in sample_chunks if c.owner_id == lecteur_ctx.user_id)
    tokens = tokenize(private.text_normalized)

    assert private.chunk_id in pipeline.bm25.search(tokens, lecteur_ctx, 30)
    assert private.chunk_id not in pipeline.bm25.search(tokens, other_lecteur_ctx, 30)
    assert private.chunk_id not in pipeline.returned(other_lecteur_ctx, private.text)


def test_real_pipeline_uses_the_real_bm25_index(pipeline: Pipeline) -> None:
    assert isinstance(pipeline.retrieval.bm25, BM25Index)
    assert pipeline.retrieval.store is pipeline.store


def test_any_ctx_sees_nothing_when_everything_is_hidden(pipeline: Pipeline) -> None:
    chunks = target_doc()
    pipeline.store.index(chunks)  # never shown
    pipeline.add_filler()
    for role in ("lecteur", "editeur", "admin"):
        ctx = make_ctx(role)
        assert chunks[0].chunk_id not in pipeline.bm25_ids(ctx)
        assert chunks[0].chunk_id not in pipeline.returned(ctx)
