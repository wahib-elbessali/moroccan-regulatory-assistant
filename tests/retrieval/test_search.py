"""Tests of src/retrieval/search.py (P2 spec §8: T12, T16, T20, and the P2-14 re-check).

Day 3 runs the pipeline against the merged Qdrant store on an in-memory Qdrant (as
``P2-C-fatima.md`` prescribes) with the deterministic ``HashModels`` of ``p2_helpers``, and a
small BM25 double so the keyword list can be set exactly. Basma's ``BM25Index`` is merged and is
checked here for signature compatibility, but wiring it in is day-4 work.

``StubStore`` and ``RecordingModels`` exist for the steps whose ordering must be observed exactly
(the re-check keeps no order, so the restored BM25 ranking cannot be asserted through a real
Qdrant round trip).
"""

import inspect
import uuid
from pathlib import Path
from typing import Any

import pytest
from p2_helpers import HashModels, hash_vector, make_ctx, make_doc
from qdrant_client import QdrantClient

from src.core.contracts import (
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    Chunk,
    InvalidInput,
    Passage,
    ServiceError,
    UserContext,
)
from src.ingestion import normalize_ar
from src.retrieval.bm25 import BM25Index
from src.retrieval.search import Bm25Searcher, ChunkStore, Retrieval, rrf
from src.retrieval.store import QdrantStore
from src.retrieval.tokenizer import tokenize

# The re-ranker in p2_helpers scores raw word overlap between the query and each chunk's text,
# so the texts below are built from the query's own words: the expected order is then exact.
QUERY = "تصريح الاجراء مخالفة"
QUERY_WORDS = QUERY.split()
OTHER_TEXT = "نص مختلف تماما"

# Four texts sharing 3, 2, 1 and 0 words with the query, so re-ranking has a single right answer.
GRADED_TEXTS = [
    " ".join(QUERY_WORDS),
    " ".join(QUERY_WORDS[:2]) + " " + OTHER_TEXT,
    QUERY_WORDS[0] + " " + OTHER_TEXT,
    OTHER_TEXT,
]


# --- Test doubles -----------------------------------------------------------------------------


class StubBm25:
    """``Bm25Searcher`` returning a fixed list of chunk IDs; records what it was asked."""

    def __init__(self, ids: list[str] | None = None) -> None:
        self.ids = list(ids or [])
        self.calls: list[tuple[list[str], str, int]] = []

    def search(self, tokens: list[str], ctx: UserContext, limit: int) -> list[str]:
        self.calls.append((tokens, ctx.role, limit))
        return self.ids[:limit]


class StubStore:
    """``ChunkStore`` with no Qdrant behind it, for the steps whose order must be observed.

    Args:
        vector_hits: What ``vector_search`` returns, already ranked.
        visible: Chunks ``recheck`` lets through, by ID. ``None`` means every chunk it is given
            that this store knows about.
        reverse_recheck: Return the re-check dict in reverse order, which a real Qdrant scroll is
            free to do (``QdrantStore.recheck``: "Order is not kept"). The pipeline must not rely
            on it.
    """

    def __init__(
        self,
        *,
        vector_hits: list[Chunk] | None = None,
        known: list[Chunk] | None = None,
        visible: set[str] | None = None,
        reverse_recheck: bool = False,
    ) -> None:
        self.vector_hits = list(vector_hits or [])
        self.known = {c.chunk_id: c for c in (known or []) + list(vector_hits or [])}
        self.visible = visible
        self.reverse_recheck = reverse_recheck
        self.calls: list[tuple[str, Any]] = []
        # What each half was actually handed, so the filter and the limits can be asserted.
        self.vector_flt: Any = None
        self.vector_limit: int | None = None
        self.recheck_flt: Any = None
        self.recheck_ids: list[str] | None = None

    def vector_search(self, vector: list[float], flt: Any, limit: int) -> list[Chunk]:
        self.vector_flt = flt
        self.vector_limit = limit
        return self.vector_hits[:limit]

    def recheck(self, chunk_ids: list[str], flt: Any) -> dict[str, Chunk]:
        self.recheck_flt = flt
        self.recheck_ids = list(chunk_ids)
        kept = [
            cid
            for cid in chunk_ids
            if cid in self.known and (self.visible is None or cid in self.visible)
        ]
        if self.reverse_recheck:
            kept.reverse()
        return {cid: self.known[cid] for cid in kept}

    def index(self, chunks: list[Chunk]) -> None:
        self.calls.append(("index", chunks))

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        self.calls.append(("update_roles", (doc_id, roles)))

    def hide(self, doc_id: str) -> None:
        self.calls.append(("hide", doc_id))

    def show(self, doc_id: str) -> None:
        self.calls.append(("show", doc_id))

    def delete(self, doc_id: str) -> None:
        self.calls.append(("delete", doc_id))


class RecordingModels:
    """A models client that records every text it is given.

    ``embed`` returns the same deterministic vectors as ``HashModels``, so this double also
    works against a real Qdrant; unlike ``HashModels`` it keeps the texts, not just the batch
    sizes, which is what the query-shape assertions need. ``rerank`` gives every candidate the
    same score unless fixed ones are supplied.
    """

    def __init__(self, *, score: float = 1.0, scores: list[float] | None = None) -> None:
        self.score = score
        self.scores = scores
        self.embed_calls: list[list[str]] = []
        self.rerank_calls: list[tuple[str, list[str]]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [hash_vector(text) for text in texts]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        self.rerank_calls.append((query, list(texts)))
        if self.scores is not None:
            return self.scores
        return [self.score for _ in texts]


class BrokenModels(RecordingModels):
    """A models client that answers with the wrong number of scores."""

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        return [1.0] * (len(texts) + 1)


# --- Fixtures ---------------------------------------------------------------------------------


@pytest.fixture
def lecteur_ctx() -> UserContext:
    """Stands in for P5's fixture, which is not merged on main yet (P5-08)."""
    return make_ctx("lecteur", uuid.UUID("11111111-1111-1111-1111-111111111111"))


@pytest.fixture
def store(qdrant: QdrantClient, collection: str) -> QdrantStore:
    s = QdrantStore(qdrant, HashModels(), collection=collection)
    s.ensure_collection()
    return s


def build(store: QdrantStore, bm25_ids: list[str] | None = None, **kwargs: Any) -> Retrieval:
    """A ``Retrieval`` on the real store, with the BM25 half stubbed (day 3)."""
    return Retrieval(store, StubBm25(bm25_ids), models=HashModels(), **kwargs)


def shown(store: QdrantStore, chunks: list[Chunk]) -> list[Chunk]:
    """Indexes a document and makes it searchable: ``index`` stores chunks hidden (P2-06)."""
    store.index(chunks)
    store.show(chunks[0].doc_id)
    return chunks


# --- T16: RRF (P2-15) -------------------------------------------------------------------------


def test_t16_rrf_orders_the_spec_example() -> None:
    """T16: two lists [a, b, c] and [c, a] with k = 60 fuse to a, c, b."""
    assert rrf([["a", "b", "c"], ["c", "a"]], 60) == ["a", "c", "b"]


def test_t16_rrf_order_follows_the_scores_the_formula_gives() -> None:
    """The spec example turns on a narrow margin: ``a`` scores 1/61 + 1/62 = 0.032522 against
    ``c``'s 1/63 + 1/61 = 0.032266, a gap of 0.00026. The expected order is derived here from
    the formula rather than written out, so a wrong accumulation, a wrong sort direction or a
    missing de-duplication all show up as a different order.

    Rank numbering itself cannot be observed this way: ``rrf`` returns IDs and no scores, and
    0-based ranks would order this example the same. The 1-based rule is pinned by the formula
    written below and by ``test_t16_rrf_orders_the_spec_example``.
    """
    lists = [["a", "b", "c"], ["c", "a"]]
    expected_scores = {
        "a": 1 / (60 + 1) + 1 / (60 + 2),  # rank 1 in the first list, rank 2 in the second
        "b": 1 / (60 + 2),  # rank 2 in the first list only
        "c": 1 / (60 + 3) + 1 / (60 + 1),  # rank 3 in the first list, rank 1 in the second
    }
    expected = sorted(expected_scores, key=lambda chunk_id: -expected_scores[chunk_id])

    assert rrf(lists, 60) == expected
    assert expected == ["a", "c", "b"]
    assert expected_scores["a"] - expected_scores["c"] < 0.001  # the margin really is narrow


def test_rrf_accumulates_an_id_present_in_several_lists() -> None:
    """A repeated ID gains one contribution per list and still appears once."""
    assert rrf([["x"], ["x"]], 60) == ["x"]
    assert rrf([["x"], ["y", "x"]], 60) == ["x", "y"]  # x: 1/61 + 1/62 > y: 1/61


def test_rrf_breaks_ties_by_first_appearance() -> None:
    """Equal scores keep the order the IDs were first met in, lists read in the order given."""
    assert rrf([["a", "b"], ["c", "d"]], 60) == ["a", "c", "b", "d"]
    assert rrf([["c", "d"], ["a", "b"]], 60) == ["c", "a", "d", "b"]


def test_rrf_is_deterministic_over_repeated_calls() -> None:
    lists = [["a", "b", "c", "d"], ["d", "c"], ["b"]]
    assert len({tuple(rrf(lists, 60)) for _ in range(20)}) == 1


def test_rrf_of_empty_lists_is_empty() -> None:
    assert rrf([], 60) == []
    assert rrf([[], []], 60) == []


def test_rrf_with_a_single_list_keeps_its_order() -> None:
    assert rrf([["a", "b", "c"]], 60) == ["a", "b", "c"]


def test_larger_k_still_prefers_agreement_between_lists() -> None:
    assert rrf([["a", "b", "c"], ["c", "a"]], 1000) == ["a", "c", "b"]


# --- T12: input validation (P2-11) ------------------------------------------------------------


def test_t12_search_without_a_context_is_invalid_input(store: QdrantStore) -> None:
    """T12: search(query, None) raises InvalidInput."""
    with pytest.raises(InvalidInput):
        build(store).search(QUERY, None)  # type: ignore[arg-type]


def test_context_is_checked_before_anything_else() -> None:
    """A missing context is refused without touching the store or the models."""
    store = StubStore()
    with pytest.raises(InvalidInput):
        Retrieval(store, StubBm25(), models=RecordingModels()).search(QUERY, None)  # type: ignore[arg-type]
    assert store.calls == []


@pytest.mark.parametrize(
    "query",
    ["", "   ", "\t\n", "...", "!!! ???", "‏‎"],
    ids=["empty", "spaces", "whitespace", "dots", "punctuation", "invisible-marks"],
)
def test_query_empty_after_normalisation_is_invalid_input(
    store: QdrantStore, lecteur_ctx: UserContext, query: str
) -> None:
    """normalize_ar drops punctuation and invisible marks, so these queries have no words."""
    assert normalize_ar(query) == ""
    with pytest.raises(InvalidInput):
        build(store).search(query, lecteur_ctx)


@pytest.mark.parametrize("top_k", [0, -1, 21, 100], ids=["zero", "negative", "above", "far-above"])
def test_top_k_outside_the_range_is_invalid_input(
    store: QdrantStore, lecteur_ctx: UserContext, top_k: int
) -> None:
    """top_k must stay within 1 … rerank_top_n (20 by default). 0 is not a default: None is."""
    with pytest.raises(InvalidInput):
        build(store).search(QUERY, lecteur_ctx, top_k)


@pytest.mark.parametrize("top_k", [1, 20], ids=["lowest", "highest"])
def test_top_k_at_the_edges_of_the_range_is_accepted(
    store: QdrantStore, lecteur_ctx: UserContext, top_k: int
) -> None:
    shown(store, make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES))
    assert build(store).search(QUERY, lecteur_ctx, top_k) != []


def test_top_k_none_uses_top_k_final(store: QdrantStore, lecteur_ctx: UserContext) -> None:
    """top_k=None means retrieval.top_k_final, which caps the result."""
    texts = [f"{QUERY} رقم {i}" for i in range(6)]
    shown(store, make_doc("public", texts=texts, roles=PUBLIC_ROLES))
    retrieval = build(store, top_k_final=4)
    assert len(retrieval.search(QUERY, lecteur_ctx)) == 4
    assert len(retrieval.search(QUERY, lecteur_ctx, 2)) == 2


def test_top_k_above_rerank_top_n_is_refused_even_when_configured_low(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    retrieval = build(store, top_k_final=2, rerank_top_n=5)
    assert retrieval.search(QUERY, lecteur_ctx, 5) == []  # in range, nothing indexed
    with pytest.raises(InvalidInput):
        retrieval.search(QUERY, lecteur_ctx, 6)


# --- T20: the final list (P2-16, P2-17) -------------------------------------------------------


def test_t20_top_k_three_returns_three_ranked_passages(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    """T20: at most 3 passages, ranks 1-2-3, scores decreasing, real Passage objects."""
    shown(store, make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES))
    passages = build(store).search(QUERY, lecteur_ctx, 3)

    assert len(passages) == 3
    assert all(isinstance(p, Passage) for p in passages)
    assert [p.rank for p in passages] == [1, 2, 3]
    scores = [p.score for p in passages]
    assert scores == sorted(scores, reverse=True)
    # The graded texts share 3, 2, 1 and 0 words with the query, so the order is exact and the
    # chunk that shares nothing is the one left out.
    assert scores == [3.0, 2.0, 1.0]
    assert [p.chunk.chunk_index for p in passages] == [0, 1, 2]


def test_fewer_matches_than_top_k_returns_what_there_is(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    """ "At most 3": two visible chunks and top_k=3 gives two passages, ranked 1 and 2."""
    shown(store, make_doc("public", texts=GRADED_TEXTS[:2], roles=PUBLIC_ROLES))
    passages = build(store).search(QUERY, lecteur_ctx, 3)
    assert [p.rank for p in passages] == [1, 2]


def test_ranks_are_consecutive_from_one(store: QdrantStore, lecteur_ctx: UserContext) -> None:
    texts = [f"{QUERY} رقم {i}" for i in range(5)]
    shown(store, make_doc("public", texts=texts, roles=PUBLIC_ROLES))
    passages = build(store).search(QUERY, lecteur_ctx, 5)
    assert [p.rank for p in passages] == [1, 2, 3, 4, 5]


def test_scores_are_non_increasing_even_when_the_reranker_ties() -> None:
    """Word-overlap re-rankers tie often, so the contract is non-increasing, not strictly
    decreasing. Ties keep the fused order."""
    chunks = make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES)
    store = StubStore(vector_hits=chunks)
    passages = Retrieval(store, StubBm25(), models=RecordingModels(score=0.5)).search(
        QUERY, make_ctx("lecteur"), 4
    )
    scores = [p.score for p in passages]
    assert scores == [0.5, 0.5, 0.5, 0.5]
    assert scores == sorted(scores, reverse=True)
    assert [p.chunk.chunk_id for p in passages] == [c.chunk_id for c in chunks]


def test_empty_store_returns_an_empty_list(store: QdrantStore, lecteur_ctx: UserContext) -> None:
    """P2-17: nothing visible matching is not an error."""
    assert build(store).search(QUERY, lecteur_ctx) == []


def test_nothing_visible_to_this_role_returns_an_empty_list(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    shown(store, make_doc("internal", texts=GRADED_TEXTS, roles=INTERNAL_ROLES))
    assert build(store).search(QUERY, lecteur_ctx) == []


def test_document_never_shown_returns_an_empty_list(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    """A document indexed but never shown stays invisible (P2-06), through the whole pipeline."""
    store.index(make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES))
    assert build(store).search(QUERY, lecteur_ctx) == []


def test_candidates_are_capped_at_rerank_top_n() -> None:
    """P2-16: only the best rerank_top_n fused chunks reach the re-ranker."""
    chunks = make_doc("public", texts=[f"{QUERY} رقم {i}" for i in range(10)], roles=PUBLIC_ROLES)
    store = StubStore(vector_hits=chunks)
    models = RecordingModels()
    Retrieval(store, StubBm25(), models=models, top_k_final=3, rerank_top_n=4).search(
        QUERY, make_ctx("lecteur"), 3
    )
    query_sent, texts_sent = models.rerank_calls[0]
    assert texts_sent == [c.text for c in chunks[:4]]  # 4 of the 10 fused, best first
    assert query_sent == QUERY  # the question as typed (P2-18)


def test_reranker_is_given_the_bare_chunk_text_not_the_embedding_text() -> None:
    """P2-16 sends ``c.text``; the title and headings of P2-07 belong to indexing only."""
    chunks = make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES)
    store = StubStore(vector_hits=chunks)
    models = RecordingModels()
    Retrieval(store, StubBm25(), models=models).search(QUERY, make_ctx("lecteur"))
    _, texts_sent = models.rerank_calls[0]
    assert texts_sent == GRADED_TEXTS
    assert not any(chunks[0].title in text for text in texts_sent)


def test_reranker_is_not_called_when_nothing_was_found() -> None:
    """An empty result costs no model call (P2-17)."""
    models = RecordingModels()
    assert (
        Retrieval(StubStore(), StubBm25(), models=models).search(QUERY, make_ctx("lecteur")) == []
    )
    assert models.rerank_calls == []


def test_reranker_scores_are_attached_to_the_right_chunks() -> None:
    """Scores come back in the order the texts went out, so the pairing is positional."""
    chunks = make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES)
    store = StubStore(vector_hits=chunks)
    models = RecordingModels(scores=[0.1, 0.9, 0.4, 0.2])
    passages = Retrieval(store, StubBm25(), models=models).search(QUERY, make_ctx("lecteur"), 4)
    assert [p.chunk.chunk_index for p in passages] == [1, 2, 3, 0]
    assert [p.score for p in passages] == [0.9, 0.4, 0.2, 0.1]


def test_wrong_number_of_reranker_scores_raises_service_error() -> None:
    """Pairing scores with the wrong chunks would be worse than failing."""
    chunks = make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES)
    store = StubStore(vector_hits=chunks)
    with pytest.raises(ServiceError):
        Retrieval(store, StubBm25(), models=BrokenModels()).search(QUERY, make_ctx("lecteur"), 3)


# --- P2-14: the BM25 re-check -----------------------------------------------------------------


def test_bm25_candidate_dropped_by_the_recheck_is_never_returned(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    """A stale BM25 list offering a hidden chunk cannot put it in the results (P2-14)."""
    visible = shown(store, make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES))
    hidden = make_doc("secret", texts=[" ".join(QUERY_WORDS)], roles=PUBLIC_ROLES)
    store.index(hidden)  # indexed, never shown

    retrieval = build(store, bm25_ids=[hidden[0].chunk_id])
    passages = retrieval.search(QUERY, lecteur_ctx, 20)

    returned = {p.chunk.chunk_id for p in passages}
    assert hidden[0].chunk_id not in returned
    assert returned == {c.chunk_id for c in visible}


def test_bm25_candidate_restricted_to_another_role_is_never_returned(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    internal = shown(store, make_doc("internal", texts=GRADED_TEXTS, roles=INTERNAL_ROLES))
    retrieval = build(store, bm25_ids=[c.chunk_id for c in internal])
    assert retrieval.search(QUERY, lecteur_ctx, 20) == []


def test_surviving_bm25_candidates_keep_their_bm25_order() -> None:
    """The re-check returns an unordered dict, so the pipeline must restore BM25's ranking:
    that position is what RRF reads as the rank. With an indifferent re-ranker, the final order
    is the fused order, so a reversed re-check must not change it."""
    chunks = make_doc("public", texts=[f"{QUERY} رقم {i}" for i in range(4)], roles=PUBLIC_ROLES)
    bm25_order = [c.chunk_id for c in chunks]

    passages = []
    for reverse in (False, True):
        store = StubStore(known=chunks, visible=set(bm25_order), reverse_recheck=reverse)
        retrieval = Retrieval(store, StubBm25(bm25_order), models=RecordingModels())
        passages.append([p.chunk.chunk_id for p in retrieval.search(QUERY, make_ctx("lecteur"), 4)])

    assert passages[0] == bm25_order
    assert passages[1] == bm25_order  # the dict's order must not leak into the ranking


def test_recheck_is_given_the_bm25_ids_and_the_same_filter_object() -> None:
    """P2-14: the re-check runs the BM25 candidates against the *same* visibility filter as the
    vector search. The filter is built once and handed to both halves, so the two must be the
    very same object — a second ``visibility_filter(ctx)`` call could drift from the first."""
    chunks = make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES)
    ids = [c.chunk_id for c in chunks]
    store = StubStore(known=chunks, visible={ids[0]})
    retrieval = Retrieval(store, StubBm25(ids), models=RecordingModels())

    passages = retrieval.search(QUERY, make_ctx("lecteur"), 4)

    assert store.recheck_ids == ids  # every BM25 candidate is re-checked, in BM25 order
    assert store.recheck_flt is store.vector_flt  # one filter, both halves
    assert store.vector_flt is not None
    assert [p.chunk.chunk_id for p in passages] == [ids[0]]  # only the survivor comes back


# --- The query reaches each half in the right shape (P2-18) -----------------------------------


def test_bm25_receives_the_normalised_tokenised_query(store: QdrantStore) -> None:
    """P2-18: BM25 gets the query after normalize_ar and tokenize; the vector half gets it raw."""
    bm25 = StubBm25()
    ctx = make_ctx("lecteur")
    typed = "المادة 12 من القانون"
    Retrieval(store, bm25, models=HashModels()).search(typed, ctx)
    tokens, role, limit = bm25.calls[0]

    # normalize_ar turns teh marbuta into heh (المادة -> الماده) and tokenize drops the stopword
    # من, so the tokens are neither the typed words nor a copy of them.
    assert tokens == tokenize(normalize_ar(typed))
    assert tokens == ["الماده", "12", "القانون"]
    assert "من" not in tokens
    assert (role, limit) == ("lecteur", 30)


@pytest.mark.parametrize(
    "typed",
    [
        "Quelles sanctions ? المادة 12",  # mixed French and Arabic, punctuation kept
        "المادة 12 من القانون",  # teh marbuta, which normalize_ar would rewrite
        "  تصريح   الاجراء  ",  # the spacing as the user typed it
    ],
    ids=["mixed", "teh-marbuta", "spacing"],
)
def test_query_is_embedded_as_typed(store: QdrantStore, typed: str) -> None:
    """P2-18: the embedding sees the question exactly as typed — bge-m3 handles Arabic, French
    and mixed text, so normalizing first would throw information away.

    The double records the texts it receives, so this asserts what the pipeline actually sent
    rather than recomputing a vector: a pipeline that embedded ``normalize_ar(query)`` instead
    would fail here, which is the whole point of P2-18.
    """
    models = RecordingModels()
    Retrieval(store, StubBm25(), models=models).search(typed, make_ctx("lecteur"))

    assert models.embed_calls == [[typed]]  # one call, one text, byte-for-byte the query
    assert models.embed_calls[0][0] != normalize_ar(typed)  # and NOT the normalized form


def test_embedding_that_returns_nothing_raises_service_error(store: QdrantStore) -> None:
    class NoVectors(RecordingModels):
        def embed(self, texts: list[str]) -> list[list[float]]:
            return []

    with pytest.raises(ServiceError):
        Retrieval(store, StubBm25(), models=NoVectors()).search(QUERY, make_ctx("lecteur"))


def test_configured_limits_are_passed_to_both_halves() -> None:
    """top_k_vector goes to the vector search and top_k_bm25 to BM25 — not swapped, and not the
    defaults. The two differ here so a swap would fail."""
    store = StubStore()
    bm25 = StubBm25()
    Retrieval(store, bm25, models=RecordingModels(), top_k_vector=5, top_k_bm25=7).search(
        QUERY, make_ctx("lecteur")
    )
    assert store.vector_limit == 5
    assert bm25.calls[0][2] == 7


def test_default_limits_are_passed_to_both_halves() -> None:
    """With nothing configured, the vector search and BM25 get the config.yaml values."""
    store = StubStore()
    bm25 = StubBm25()
    Retrieval(store, bm25, models=RecordingModels()).search(QUERY, make_ctx("lecteur"))
    assert store.vector_limit == 30  # retrieval.top_k_vector
    assert bm25.calls[0][2] == 30  # retrieval.top_k_bm25


# --- Indexing and rights delegate to the store (00-shared §9) ---------------------------------


def test_index_and_rights_methods_delegate_to_the_store() -> None:
    """The store owns every write; Retrieval adds no logic of its own."""
    store = StubStore()
    retrieval = Retrieval(store, StubBm25(), models=RecordingModels())
    chunks = make_doc("public", roles=PUBLIC_ROLES)

    retrieval.index(chunks)
    retrieval.update_roles("doc", PUBLIC_ROLES)
    retrieval.hide("doc")
    retrieval.show("doc")
    retrieval.delete("doc")

    assert [name for name, _ in store.calls] == [
        "index",
        "update_roles",
        "hide",
        "show",
        "delete",
    ]
    assert store.calls[0][1] == chunks
    assert store.calls[1][1] == ("doc", PUBLIC_ROLES)


def test_rights_methods_work_through_the_real_store(
    store: QdrantStore, lecteur_ctx: UserContext
) -> None:
    """hide / show / update_roles / delete, seen through search (T6, T7, T8 on the pipeline)."""
    chunks = shown(store, make_doc("internal", texts=GRADED_TEXTS, roles=INTERNAL_ROLES))
    retrieval = build(store)
    doc_id = chunks[0].doc_id

    assert retrieval.search(QUERY, lecteur_ctx, 20) == []
    retrieval.update_roles(doc_id, PUBLIC_ROLES)
    assert retrieval.search(QUERY, lecteur_ctx, 20) != []
    retrieval.hide(doc_id)
    assert retrieval.search(QUERY, lecteur_ctx, 20) == []
    retrieval.show(doc_id)
    assert retrieval.search(QUERY, lecteur_ctx, 20) != []
    retrieval.delete(doc_id)
    assert retrieval.search(QUERY, lecteur_ctx, 20) == []


# --- Construction -----------------------------------------------------------------------------


def test_models_client_falls_back_to_the_one_the_store_carries(store: QdrantStore) -> None:
    """``Retrieval(store, bm25)`` — the wiring agreed in P2-common.md — stays valid."""
    retrieval = Retrieval(store, StubBm25())
    assert retrieval.models is store.models


def test_missing_models_client_is_refused() -> None:
    with pytest.raises(ValueError):
        Retrieval(StubStore(), StubBm25())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k_vector": 0},
        {"top_k_bm25": 0},
        {"top_k_final": 0},
        {"rerank_top_n": 0},
        {"rrf_k": 0},
        {"top_k_final": 10, "rerank_top_n": 5},
    ],
    ids=["vector", "bm25", "final", "rerank", "rrf_k", "rerank-below-final"],
)
def test_impossible_configuration_is_refused(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Retrieval(StubStore(), StubBm25(), models=RecordingModels(), **kwargs)


def test_defaults_match_config_yaml() -> None:
    """The defaults stand in for cfg.retrieval until P5's config loader lands."""
    retrieval = Retrieval(StubStore(), StubBm25(), models=RecordingModels())
    assert (retrieval.top_k_vector, retrieval.top_k_bm25, retrieval.rrf_k) == (30, 30, 60)
    assert (retrieval.top_k_final, retrieval.rerank_top_n) == (10, 20)


# --- The merged implementations fit the seams the pipeline declares ----------------------------


def _params(method: Any) -> list[str]:
    return list(inspect.signature(method).parameters)


def test_real_bm25_index_matches_the_searcher_protocol(tmp_path: Path) -> None:
    """Basma's merged BM25Index can be injected as it is on day 4, with no adapter."""
    assert _params(BM25Index.search) == _params(Bm25Searcher.search)
    index = BM25Index(lambda: [], tmp_path / "retrieval.version")
    assert index.search(["x"], make_ctx("lecteur"), 30) == []


def test_real_qdrant_store_matches_the_chunk_store_protocol() -> None:
    """Wahib's merged QdrantStore is what the pipeline is built on; its signatures must match."""
    for name in ("vector_search", "recheck", "index", "update_roles", "hide", "show", "delete"):
        assert _params(getattr(QdrantStore, name)) == _params(getattr(ChunkStore, name)), name


def test_logs_hold_no_query_or_chunk_text(
    store: QdrantStore, lecteur_ctx: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    """P2-29: no query, chunk text or title in any log line a search produces.

    ``search.py`` logs nothing yet — the one JSON line per search is day-5 work — so today this
    only covers what the store logs underneath (doc ids and counts). It is kept as the guard
    that day 5's log line has to keep passing, and as T22's starting point.
    """
    shown(store, make_doc("public", texts=GRADED_TEXTS, roles=PUBLIC_ROLES))
    with caplog.at_level("DEBUG"):
        build(store).search(QUERY, lecteur_ctx, 3)
    blob = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (QUERY, *GRADED_TEXTS, "عنوان public"):
        assert secret not in blob
