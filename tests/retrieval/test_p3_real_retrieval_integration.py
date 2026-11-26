"""P3's ``search_node`` against the **real** ``Retrieval`` (the Day 7 integration gap).

``tests/retrieval/test_search_route.py`` proves that the route and P3's graph read the same
factory, and ``tests/agents/orchestrator/test_orchestrator_graph.py`` proves that P3 calls
whatever the registry hands it — but both work on a stub. Nothing executed P3's own node against
the real pipeline. This file does exactly that, and nothing more:

    src/agents/orchestrator/graph.py:search_node
        -> get_retrieval()                      # the official registry, overridden per test
        -> src/retrieval/search.py:Retrieval    # the real class, not FakeRetrieval
        -> src/retrieval/store.py:QdrantStore   # the real store, on QdrantClient(":memory:")
        -> src/retrieval/bm25.py:BM25Index      # the real index, on a tmp_path version file
        -> list[Passage]

**What is real here:** P3's node, the ``Retrieval`` pipeline (input checks, visibility filter,
vector search, BM25, the P2-14 re-check, RRF, re-ranking, the P2-29 log line), ``QdrantStore``
and its filters, ``BM25Index``, the tokenizer, and the registry.

**What is not, and why:** the embeddings and the re-ranker are ``p2_helpers.HashModels`` — the
deterministic double every P2 test on the real store already uses. bge-m3 is a 1024-dimension
model served by P6 over HTTP; loading it would mean Docker, a download and about a minute per
search. So this test says nothing about retrieval *quality* or about cross-language search: that
is T23's job (``test_t23_cross_language.py``), on the real models, and it is a different claim.
What this test does establish is that the **plumbing** holds: P3 drives the real pipeline, gets
real ``Passage`` objects out of real Qdrant, and the visibility rule survives the trip.

Because ``HashModels`` embeds a hash of the text, the vector half returns *every* visible chunk
of this tiny corpus in an arbitrary order; ``HashModels.rerank`` then scores by how many query
words a chunk contains, which is what makes the final order predictable. That is a stroke of
luck for an access test: since nothing is dropped for being irrelevant, and the corpus is kept
smaller than ``top_k``, a chunk missing from the results can only have been filtered out by the
visibility rule — never truncated away.

Isolation: ``QdrantClient(":memory:")`` always, even in CI. This is the one P2 file that does
*not* use the shared ``qdrant`` fixture of ``tests/retrieval/conftest.py``, which prefers
``CI_QDRANT_URL`` when it is set: no server is contacted here, by design. Nothing outside
``tmp_path`` and the in-process client is written, and the ``_fresh_registry`` fixture of
``tests/conftest.py`` removes the override after every test.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from p2_helpers import HashModels, make_doc
from qdrant_client import QdrantClient

from src.agents.orchestrator.graph import search_node
from src.core.config import cfg
from src.core.contracts import (
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    Chunk,
    Passage,
    ProcessEvent,
    UserContext,
    registry,
)
from src.core.contracts.fakes.retrieval import FakeRetrieval
from src.core.contracts.registry import get_retrieval
from src.ingestion import normalize_ar
from src.retrieval.bm25 import BM25Index
from src.retrieval.search import Retrieval
from src.retrieval.store import QdrantStore, visibility_filter
from src.retrieval.tokenizer import tokenize
from src.retrieval.version import bump_version

# The query, already normalized, so that HashModels.rerank — which splits the raw query on
# whitespace — counts the same words BM25 sees. Four words: the chunk that carries all four is
# re-ranked above the ones that carry two, which is what makes rank 1 deterministic.
QUERY = normalize_ar("معالجة الطلبات داخل الاجل")
QUERY_WORDS = QUERY.split()

# The one chunk that holds every query word: rank 1 for anyone allowed to see it.
TOP_TEXT = normalize_ar("يتعين على المصالح معالجة الطلبات داخل الاجل القانوني")
# Same two words in each of the three others, so none of them can outrank TOP_TEXT.
PUBLIC_SECOND_TEXT = normalize_ar("فقرة عامة اخرى بدون اي علاقة بالموضوع")
INTERNAL_TEXT = normalize_ar("مذكرة داخلية حول معالجة الطلبات المستعجلة")
OWN_UPLOAD_TEXT = normalize_ar("ملف شخصي يتضمن معالجة الطلبات الخاصة")
OTHER_UPLOAD_TEXT = normalize_ar("ملف مستخدم اخر حول معالجة الطلبات")

FILLER_DOCS = 5  # public chunks with none of the query words (see Corpus.visible_for)


class Corpus:
    """The real three objects, wired as ``real_retrieval()`` wires them, plus the test corpus.

    Documents, and who may see each one (00-shared §6.3):

    | document   | chunks | rights                 | visible to                      |
    |------------|--------|------------------------|---------------------------------|
    | ``public`` | 2      | ``PUBLIC_ROLES``       | every ``lecteur`` and ``editeur``|
    | ``internal``| 1     | ``INTERNAL_ROLES``     | ``editeur`` only                |
    | ``own``    | 1      | none, owned by lecteur | that one ``lecteur``            |
    | ``other``  | 1      | none, owned by another | that other ``lecteur``          |
    | ``filler-*``| 5     | ``PUBLIC_ROLES``       | every ``lecteur`` and ``editeur``|

    An ``admin`` is in no ``allowed_roles`` and owns nothing, so an admin sees none of it — the
    rule of 00-shared §6.3, not an accident of this corpus.
    """

    def __init__(self, qdrant: QdrantClient, collection: str, version_file: Path) -> None:
        self.models = HashModels()
        self.store = QdrantStore(
            qdrant,
            self.models,
            collection=collection,
            embed_batch_size=cfg.retrieval.embed_batch_size,
            on_write=lambda: bump_version(version_file),
        )
        self.store.ensure_collection()
        self.bm25 = BM25Index(load_payloads=self.store.scroll_payloads, version_file=version_file)
        # The real pipeline, built from config.yaml exactly as real_retrieval() builds it.
        self.retrieval = Retrieval(
            self.store,
            self.bm25,
            models=self.models,
            top_k_vector=cfg.retrieval.top_k_vector,
            top_k_bm25=cfg.retrieval.top_k_bm25,
            rrf_k=cfg.retrieval.rrf_k,
            top_k_final=cfg.retrieval.top_k_final,
            rerank_top_n=cfg.retrieval.rerank_top_n,
        )
        self.docs: dict[str, list[Chunk]] = {}

    def add(self, name: str, chunks: list[Chunk]) -> list[Chunk]:
        """Indexes a document and makes it searchable: ``index`` stores chunks hidden (P2-06)."""
        self.store.index(chunks)
        self.store.show(chunks[0].doc_id)
        self.docs[name] = chunks
        return chunks

    def ids(self, *names: str) -> set[str]:
        return {chunk.chunk_id for name in names for chunk in self.docs[name]}

    @property
    def filler_names(self) -> list[str]:
        return [f"filler-{i}" for i in range(FILLER_DOCS)]

    def visible_for(self, name: str) -> set[str]:
        """The chunk IDs a given user must get back — every visible chunk, nothing dropped.

        ``HashModels`` embeds a hash, so the vector half ranks by nothing in particular and
        returns the whole visible corpus; the chunk IDs below are therefore an exact expectation,
        not a subset. Eight is under ``top_k_final`` (10), so no result is ever truncated and an
        absent chunk means the visibility filter removed it.
        """
        shared = ("public", *self.filler_names)
        by_user = {
            "lecteur": self.ids(*shared, "own"),
            "other_lecteur": self.ids(*shared, "other"),
            "editeur": self.ids(*shared, "internal"),
            "admin": set(),
        }
        return by_user[name]


@pytest.fixture
def memory_qdrant() -> Iterator[QdrantClient]:
    """An in-memory Qdrant, closed afterwards. Never a server, not even CI's (see the module
    docstring): this test must be hermetic, and the team's instance is never touched."""
    client = QdrantClient(":memory:")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def corpus(
    memory_qdrant: QdrantClient,
    tmp_path: Path,
    lecteur_ctx: UserContext,
    other_lecteur_ctx: UserContext,
) -> Corpus:
    """The real pipeline over the corpus above, installed in the registry under "retrieval".

    ``registry.override`` is the official injection point (00-shared §9) and the very mechanism
    ``get_retrieval()`` reads, so P3's production code is driven unchanged.
    """
    built = Corpus(memory_qdrant, f"p3_integration_{tmp_path.name}", tmp_path / "retrieval.version")

    built.add(
        "public", make_doc("public", texts=[TOP_TEXT, PUBLIC_SECOND_TEXT], roles=PUBLIC_ROLES)
    )
    built.add("internal", make_doc("internal", texts=[INTERNAL_TEXT], roles=INTERNAL_ROLES))
    built.add("own", make_doc("own", texts=[OWN_UPLOAD_TEXT], owner_id=lecteur_ctx.user_id))
    built.add(
        "other", make_doc("other", texts=[OTHER_UPLOAD_TEXT], owner_id=other_lecteur_ctx.user_id)
    )
    # Without chunks that lack the query words, BM25Okapi scores everything negatively on a
    # corpus this small and returns nothing (see test_hybrid.py).
    for name in built.filler_names:
        built.add(
            name,
            make_doc(name, texts=[normalize_ar(f"موضوع مختلف رقم {name}")], roles=PUBLIC_ROLES),
        )

    registry.override("retrieval", built.retrieval)
    return built


def run_node(ctx: UserContext, query: str = QUERY) -> tuple[dict[str, Any], list[ProcessEvent]]:
    """P3's own ``search_node``, on the state its graph gives it. Nothing here is a copy of it."""
    events: list[ProcessEvent] = []
    state = {
    "query": query,
    "question": query,
    "current_index": 0,
    "iteration": 1,
    "ctx": ctx,
    "tokens": 0,
    "emit": events.append,
}
    return search_node(state), events  # type: ignore[arg-type]


def passages_of(result: dict[str, Any]) -> list[Passage]:
    return result["last_passages"]


# --- The node really drives the real class ----------------------------------------------------


def test_the_node_runs_the_real_retrieval_class(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """What ``get_retrieval()`` hands P3 is ``src.retrieval.search.Retrieval``, not a fake."""
    installed = get_retrieval()

    assert isinstance(installed, Retrieval)
    assert not isinstance(installed, FakeRetrieval)
    assert installed is corpus.retrieval
    # The real class owns the real store and the real index.
    assert isinstance(installed.store, QdrantStore)
    assert isinstance(installed.bm25, BM25Index)

    result, _ = run_node(lecteur_ctx)

    assert passages_of(result), "the real pipeline returned nothing at all"


def test_the_query_reaches_the_real_pipeline(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """The node's query is embedded by the pipeline and searched for in Qdrant.

    ``embed_calls`` records one entry per call with its batch size. Indexing the corpus made
    several; the search adds exactly one more, of one text — the query (P2-18, embedded as
    typed). That call can only come from ``Retrieval._embed``.
    """
    before = len(corpus.models.embed_calls)

    run_node(lecteur_ctx)

    assert corpus.models.embed_calls[before:] == [1]


def test_both_halves_of_the_hybrid_search_are_live(
    corpus: Corpus, lecteur_ctx: UserContext
) -> None:
    """Vector search and BM25 both answer: the fusion is fed by two real lists.

    Asked directly, outside the node, so this is about the pipeline's inputs and not about what
    the node does with them.
    """
    vector = corpus.store.vector_search(
        corpus.models.embed([QUERY])[0],
        visibility_filter(lecteur_ctx),
        cfg.retrieval.top_k_vector,
    )
    bm25_ids = corpus.bm25.search(tokenize(QUERY), lecteur_ctx, cfg.retrieval.top_k_bm25)
    top_id = next(iter(corpus.ids("public") & {c.chunk_id for c in vector}), None)

    assert vector, "the real vector search returned nothing"
    assert bm25_ids, "the real BM25 index returned nothing"
    assert top_id is not None
    # BM25 found the chunk that holds every query word, so the lexical half is doing real work.
    assert corpus.docs["public"][0].chunk_id in bm25_ids


# --- The results are a real, ranked, usable Passage list ---------------------------------------


def test_the_expected_chunks_come_back(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """Exactly the chunks this lecteur may see, and the best match first."""
    result, _ = run_node(lecteur_ctx)
    passages = passages_of(result)

    assert {p.chunk.chunk_id for p in passages} == corpus.visible_for("lecteur")
    # TOP_TEXT holds all four query words; every other visible match holds two.
    assert passages[0].chunk.chunk_id == corpus.docs["public"][0].chunk_id
    assert passages[0].chunk.text == TOP_TEXT


def test_the_ranks_and_scores_are_valid(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """``rank`` is 1, 2, 3… and ``score`` never increases (P2-16, P2-17)."""
    passages = passages_of(run_node(lecteur_ctx)[0])

    assert all(isinstance(p, Passage) for p in passages)
    assert [p.rank for p in passages] == list(range(1, len(passages) + 1))
    scores = [p.score for p in passages]
    assert scores == sorted(scores, reverse=True)
    assert len(passages) <= cfg.retrieval.top_k_final


def test_the_passages_are_what_p3s_later_nodes_expect(
    corpus: Corpus, lecteur_ctx: UserContext
) -> None:
    """The real objects carry every field the rest of the graph reads.

    ``grade_node`` builds its prompt from ``p.chunk.text``, keys its accumulator on
    ``p.chunk.chunk_id`` and compares ``p.score``; ``search_node`` and ``grade_node`` label
    passages with ``p.chunk.title`` and ``p.chunk.article``. A real ``Chunk`` from Qdrant has to
    survive all of that — a round trip through a payload is where a field goes missing.
    """
    passages = passages_of(run_node(lecteur_ctx)[0])

    assert all(p.chunk.text and p.chunk.text_normalized and p.chunk.title for p in passages)
    assert all(p.chunk.language == "ar" and p.chunk.source_file for p in passages)
    assert all(p.chunk.page_start >= 1 and p.chunk.page_end >= p.chunk.page_start for p in passages)
    # grade_node's own two operations, run for real on real passages.
    by_id = {p.chunk.chunk_id: p for p in passages}
    assert len(by_id) == len(passages)  # chunk_id is unique, so it is a usable key
    assert all(isinstance(p.score, float) for p in passages)
    assert list(dict.fromkeys(f"{p.chunk.title} — {p.chunk.article or ''}" for p in passages))


def test_the_node_emits_the_search_process_event(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """One ``search`` event, whose counts describe the real result (00-shared §5.7)."""
    result, events = run_node(lecteur_ctx)
    passages = passages_of(result)

    assert len(events) == 1
    event = events[0]
    assert event.step == "search"
    assert event.data["query"] == QUERY
    assert event.data["count"] == len(passages)
    assert event.data["titles"] == list(dict.fromkeys(p.chunk.title for p in passages))


# --- The visibility rule survives the trip through P3 ------------------------------------------


@pytest.mark.parametrize(
    "user",
    ["lecteur", "other_lecteur", "editeur", "admin"],
)
def test_access_control_is_preserved_through_the_node(
    corpus: Corpus, request: pytest.FixtureRequest, user: str
) -> None:
    """Each role gets exactly its visible chunks — filtered inside Qdrant, before scoring.

    The expectation is an equality, not a subset: see ``Corpus.visible_for``. An ``admin`` is in
    no ``allowed_roles`` and owns nothing, so an admin gets ``[]`` — a normal empty result
    (P2-17), not an error.
    """
    ctx: UserContext = request.getfixturevalue(f"{user}_ctx")

    result, events = run_node(ctx)
    returned = {p.chunk.chunk_id for p in passages_of(result)}

    assert returned == corpus.visible_for(user)
    assert len(returned) < cfg.retrieval.top_k_final  # so nothing above was truncated away
    assert events[0].data["count"] == len(returned)


def test_the_internal_document_never_reaches_a_lecteur(
    corpus: Corpus, lecteur_ctx: UserContext, editeur_ctx: UserContext
) -> None:
    """The same query, two roles: the internal note is in one answer and not in the other.

    Its text must not appear anywhere in the lecteur's passages either — not only its chunk ID.
    """
    lecteur_passages = passages_of(run_node(lecteur_ctx)[0])
    editeur_passages = passages_of(run_node(editeur_ctx)[0])
    internal_id = corpus.docs["internal"][0].chunk_id

    assert internal_id not in {p.chunk.chunk_id for p in lecteur_passages}
    assert internal_id in {p.chunk.chunk_id for p in editeur_passages}
    assert all(INTERNAL_TEXT not in p.chunk.text for p in lecteur_passages)


def test_a_private_upload_is_matched_on_the_owners_user_id(
    corpus: Corpus, lecteur_ctx: UserContext, other_lecteur_ctx: UserContext
) -> None:
    """Two users of the same role, one upload each: ``ctx.user_id`` is what tells them apart.

    This is what proves the authenticated context — and not merely the role — reached the filter
    Qdrant applied.
    """
    own_id = corpus.docs["own"][0].chunk_id
    other_id = corpus.docs["other"][0].chunk_id

    mine = {p.chunk.chunk_id for p in passages_of(run_node(lecteur_ctx)[0])}
    theirs = {p.chunk.chunk_id for p in passages_of(run_node(other_lecteur_ctx)[0])}

    assert lecteur_ctx.role == other_lecteur_ctx.role == "lecteur"
    assert own_id in mine and other_id not in mine
    assert other_id in theirs and own_id not in theirs


def test_hiding_the_document_again_removes_it(corpus: Corpus, lecteur_ctx: UserContext) -> None:
    """``hide`` through the real store takes the chunk out of the node's results (P2-24).

    The node is run before and after, so this also shows the pipeline is read live on every
    call and nothing is cached behind P3's back.
    """
    top_id = corpus.docs["public"][0].chunk_id
    assert top_id in {p.chunk.chunk_id for p in passages_of(run_node(lecteur_ctx)[0])}

    corpus.retrieval.hide(corpus.docs["public"][0].doc_id)

    assert top_id not in {p.chunk.chunk_id for p in passages_of(run_node(lecteur_ctx)[0])}


# --- Nothing leaks into the logs ---------------------------------------------------------------


def test_no_query_or_chunk_text_is_logged(
    corpus: Corpus, lecteur_ctx: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    """P2-29 and T22 hold on the real pipeline *and* on P3's node log line.

    Both log one structured line per search. Neither may carry the question or a chunk's text,
    and this checks every record captured, message and ``extra`` fields alike. The ``search``
    process event does carry the query — it goes to the narrator, not to a log — so only log
    records are read here.
    """
    import logging

    with caplog.at_level(logging.DEBUG):
        passages = passages_of(run_node(lecteur_ctx)[0])
    assert passages, "nothing was found, so nothing would have been logged either"

    blob = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    for secret in (QUERY, TOP_TEXT, OWN_UPLOAD_TEXT, passages[0].chunk.title):
        assert secret not in blob, secret
