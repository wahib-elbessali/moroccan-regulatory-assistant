"""Hybrid search: RRF fusion, re-ranking and the final ``Passage`` list (P2 spec §3.3, §6.2).

The pipeline joins the two halves of the search, each owned by another slice of P2:

    check inputs (P2-11) -> visibility_filter(ctx)
    -> store.vector_search(embed([query])[0], flt, top_k_vector)     # meaning, filter inside
    -> bm25.search(tokenize(normalize_ar(query)), ctx, top_k_bm25)   # keywords, filter inside
    -> store.recheck(bm25 ids, flt)                                  # P2-14
    -> rrf([vector ids, bm25 ids], rrf_k)[:rerank_top_n]             # P2-15
    -> models.rerank(query, [c.text for c in candidates])            # P2-16
    -> top_k Passages, rank 1, 2, 3 ...                              # P2-17

The visibility rule (00-shared §6.3) is applied **inside** both indexes, before scoring: this
module never filters results afterwards. The query is embedded as typed and given to BM25
normalized and tokenized (P2-18).

When a model is down the search degrades instead of failing (P2-19): no embeddings means BM25
only, no re-ranker means the RRF order with the RRF scores. Qdrant has no fallback — the
visibility filter cannot be checked without it — so its failures stay ``ServiceError`` (§7).

Log lines and error messages never contain the query, chunk text or a document title (P2-29).
Only the two fallback warnings are logged here; the one JSON line per search that P2-29 also asks
for is day-5 work (``P2-C-fatima.md``).
"""

import logging
from collections import defaultdict
from typing import Protocol

from qdrant_client import models as qdrant_models

from src.core.contracts import (
    Chunk,
    InvalidInput,
    ModelsClient,
    Passage,
    ServiceError,
    UserContext,
)
from src.ingestion import normalize_ar

from .store import visibility_filter
from .tokenizer import tokenize

logger = logging.getLogger(__name__)

# Defaults mirror config.yaml, for callers that build a ``Retrieval`` directly (tests, scripts).
# ``real_retrieval()`` reads the values from ``cfg.retrieval`` and passes them in, so this module
# never imports the configuration itself.
DEFAULT_TOP_K_VECTOR = 30  # retrieval.top_k_vector
DEFAULT_TOP_K_BM25 = 30  # retrieval.top_k_bm25
DEFAULT_RRF_K = 60  # retrieval.rrf_k
DEFAULT_TOP_K_FINAL = 10  # retrieval.top_k_final
DEFAULT_RERANK_TOP_N = 20  # retrieval.rerank_top_n


class ChunkStore(Protocol):
    """What the pipeline needs from the Qdrant store (slice A, ``store.py:QdrantStore``).

    Declared structurally so this module depends on the agreed signatures rather than on the
    class, which keeps the pipeline testable on its own. ``QdrantStore`` satisfies it as merged.
    """

    def vector_search(
        self, vector: list[float], flt: qdrant_models.Filter, limit: int
    ) -> list[Chunk]: ...

    def recheck(self, chunk_ids: list[str], flt: qdrant_models.Filter) -> dict[str, Chunk]: ...

    def index(self, chunks: list[Chunk]) -> None: ...

    def update_roles(self, doc_id: str, roles: list[str]) -> None: ...

    def hide(self, doc_id: str) -> None: ...

    def show(self, doc_id: str) -> None: ...

    def delete(self, doc_id: str) -> None: ...


class Bm25Searcher(Protocol):
    """What the pipeline needs from the BM25 index (slice B, ``bm25.py:BM25Index``).

    ``BM25Index`` satisfies it as merged; a test double with the same one method does too.
    """

    def search(self, tokens: list[str], ctx: UserContext, limit: int) -> list[str]: ...


def _rrf_scores(lists: list[list[str]], k: int) -> dict[str, float]:
    """The fused chunk IDs with their RRF scores, best first (P2-15).

    Does the whole of the fusion; ``rrf`` is the view of it that keeps only the order. The scores
    are needed when the re-ranker is down, since they then become ``Passage.score`` (P2-19).

    Args:
        lists: Ranked lists of chunk IDs, best first.
        k: The RRF constant (``retrieval.rrf_k``).

    Returns:
        ``{chunk_id: score}``, inserted by decreasing score, so iterating it gives the ranking.
        Dicts keep insertion order, so this mapping and ``rrf`` can never disagree.
    """
    scores: defaultdict[str, float] = defaultdict(float)
    for ranked in lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return {chunk_id: scores[chunk_id] for chunk_id in sorted(scores, key=lambda c: -scores[c])}


def rrf(lists: list[list[str]], k: int) -> list[str]:
    """Fuses ranked lists of chunk IDs with Reciprocal Rank Fusion (P2-15).

    ``score(c) = sum over the lists of 1 / (k + rank_in_list(c))``, with **1-based** ranks. A
    chunk that appears in several lists accumulates one contribution per list, and appears once
    in the result. A chunk missing from a list simply contributes nothing for it.

    Ties keep the order in which the IDs were first met, reading the lists in the order given
    and each list best-first: ``sorted`` is stable and a ``dict`` keeps insertion order, so the
    same input always gives the same output. In practice the vector list therefore wins ties
    against the BM25 list.

    An ID repeated inside one list would be counted once per occurrence. Neither input can hold
    duplicates — Qdrant returns distinct points and BM25 returns distinct chunk IDs — so this is
    left as the formula says rather than guarded against.

    Args:
        lists: Ranked lists of chunk IDs, best first. Usually the vector list and the BM25 list.
        k: The RRF constant (``retrieval.rrf_k``, 60). A larger ``k`` flattens the weight of the
            top positions, so agreement between the lists counts for more than depth in one.

    Returns:
        Every distinct chunk ID, by decreasing fused score. ``[]`` if every list is empty.
    """
    return list(_rrf_scores(lists, k))


class Retrieval:
    """``Retrieval`` (00-shared §6.3) over Qdrant and BM25.

    ``index`` and the rights methods delegate to the store, which owns every write. ``search``
    is the pipeline described at the top of this module.

    Args:
        store: The Qdrant store (slice A).
        bm25: The BM25 index (slice B).
        models: Where embeddings and re-ranking come from (``get_models()``). P2 never loads a
            model. Optional: when it is not given, the store's own client is used, so the wiring
            agreed in ``P2-common.md`` — ``Retrieval(store, bm25)`` — keeps working.
        top_k_vector: Chunks asked of the vector search (``retrieval.top_k_vector``).
        top_k_bm25: Chunk IDs asked of BM25 (``retrieval.top_k_bm25``).
        rrf_k: The RRF constant (``retrieval.rrf_k``).
        top_k_final: Default number of passages ``search`` returns (``retrieval.top_k_final``).
        rerank_top_n: Fused chunks sent to the re-ranker, and the largest ``top_k`` ``search``
            accepts (``retrieval.rerank_top_n``).

    Raises:
        ValueError: No models client could be found, a limit is below 1, or ``rerank_top_n`` is
            below ``top_k_final`` (which would make the default ``top_k`` out of range).
    """

    def __init__(
        self,
        store: ChunkStore,
        bm25: Bm25Searcher,
        *,
        models: ModelsClient | None = None,
        top_k_vector: int = DEFAULT_TOP_K_VECTOR,
        top_k_bm25: int = DEFAULT_TOP_K_BM25,
        rrf_k: int = DEFAULT_RRF_K,
        top_k_final: int = DEFAULT_TOP_K_FINAL,
        rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    ) -> None:
        resolved = models if models is not None else getattr(store, "models", None)
        if resolved is None:
            raise ValueError("a models client is required: pass models=, or a store carrying one")
        if min(top_k_vector, top_k_bm25, top_k_final, rerank_top_n) < 1:
            raise ValueError("top_k_vector, top_k_bm25, top_k_final and rerank_top_n must be >= 1")
        if rrf_k < 1:
            raise ValueError("rrf_k must be at least 1")
        if rerank_top_n < top_k_final:
            raise ValueError("rerank_top_n must be at least top_k_final")
        self.store = store
        self.bm25 = bm25
        self.models: ModelsClient = resolved
        self.top_k_vector = top_k_vector
        self.top_k_bm25 = top_k_bm25
        self.rrf_k = rrf_k
        self.top_k_final = top_k_final
        self.rerank_top_n = rerank_top_n

    # --- Search (§3.3, §6.2) ------------------------------------------------------------------

    def search(self, query: str, ctx: UserContext, top_k: int | None = None) -> list[Passage]:
        """The best passages this user is allowed to see, best first (P2-11…P2-19).

        ``score`` is the re-ranker's score, so it is only comparable within one call. When the
        re-ranker is down it is the RRF score instead (P2-19), which is a much smaller number —
        around 0.03 for a chunk ranked top of both lists, since it is a sum of ``1 / (60 + rank)``
        terms. The two kinds of score are never comparable with each other, only within one call.

        Args:
            query: The question as typed. It is embedded unchanged (P2-18) and normalized and
                tokenized for BM25.
            ctx: The user's context. Required: it carries the visibility rule.
            top_k: How many passages to return; ``None`` means ``top_k_final``.

        Returns:
            At most ``top_k`` passages, ``rank`` 1, 2, 3…, by decreasing score. ``[]`` when
            nothing visible matches — an empty result is not an error (P2-17).

        Raises:
            InvalidInput: ``ctx`` is None, the query is empty after ``normalize_ar``, or ``top_k``
                is outside ``1 … rerank_top_n`` (``top_k=0`` included: only ``None`` is a
                default).
            ServiceError: Qdrant is unreachable — the visibility filter cannot be checked without
                it, so there is no fallback (§7) and an empty result is never substituted. Also
                when a model answered but made no sense (no vector, the wrong number of scores):
                that is a broken answer, not an unavailable service, and pairing scores with the
                wrong chunks would be worse than failing. A model that is simply **down** raises
                nothing here: it is handled by the fallbacks of P2-19.
        """
        if ctx is None:
            raise InvalidInput("user context required")
        normalized = normalize_ar(query)
        if not normalized:
            raise InvalidInput("empty query")
        limit = self.top_k_final if top_k is None else top_k
        if not 1 <= limit <= self.rerank_top_n:
            raise InvalidInput("top_k out of range")

        flt = visibility_filter(ctx)
        # P2-19: no embeddings means no vector half at all — Qdrant is not asked for a search it
        # has no vector for — and the search carries on with BM25 only.
        vector = self._embed(query)
        vector_hits = (
            self.store.vector_search(vector, flt, self.top_k_vector) if vector is not None else []
        )
        bm25_ids = self.bm25.search(tokenize(normalized), ctx, self.top_k_bm25)

        # P2-14: BM25 lives in memory and can be a moment behind Qdrant. recheck() returns a dict
        # and does not keep order, so the surviving IDs are put back in BM25's ranking — their
        # position in that list is what RRF reads as their rank.
        rechecked = self.store.recheck(bm25_ids, flt)
        bm25_ids = [chunk_id for chunk_id in bm25_ids if chunk_id in rechecked]

        # Both sources already carry the chunks, so the fused IDs need no further Qdrant call.
        by_id = {chunk.chunk_id: chunk for chunk in vector_hits} | rechecked
        fused = _rrf_scores([[chunk.chunk_id for chunk in vector_hits], bm25_ids], self.rrf_k)
        candidates = [by_id[chunk_id] for chunk_id in list(fused)[: self.rerank_top_n]]
        if not candidates:
            return []

        scores = self._rerank(query, candidates)
        if scores is None:
            # P2-19: the re-ranker is down. The candidates are already in fused order, so keeping
            # it needs no sort, and each one carries its own RRF score.
            ranked = [(chunk, fused[chunk.chunk_id]) for chunk in candidates]
        else:
            # Stable sort: equal re-ranker scores keep the RRF order, the sensible tie-break.
            ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: -pair[1])
        return [
            Passage(chunk=chunk, score=score, rank=rank)
            for rank, (chunk, score) in enumerate(ranked[:limit], start=1)
        ]

    def _embed(self, query: str) -> list[float] | None:
        """The query's vector, embedded as typed (P2-08, P2-18).

        The ``try`` covers the model call and nothing else: a service that answers with a wrong
        number of vectors is not a service that is down, and that answer must still fail (§7).

        Returns:
            The vector, or ``None`` when the embedding service is unavailable, which tells the
            caller to run on BM25 alone (P2-19).

        Raises:
            ServiceError: The service answered, but with a number of vectors other than one.
        """
        try:
            vectors = self.models.embed([query])  # P6
        except ServiceError:
            # No query text in the warning (P2-29); the exception itself is not logged either,
            # since P6 is free to put the request in its message.
            logger.warning(
                "embeddings unavailable, falling back to BM25 only", extra={"stage": "embed"}
            )
            return None
        if len(vectors) != 1:
            raise ServiceError("embedding service returned an unexpected number of vectors")
        return vectors[0]

    def _rerank(self, query: str, candidates: list[Chunk]) -> list[float] | None:
        """Re-ranker scores for the candidates, in the same order (P2-16).

        The bare ``text`` of each chunk is sent, not its embedding text: the re-ranker reads the
        question and the passage together, and the headings would only add noise.

        As in ``_embed``, the ``try`` covers the model call alone: a wrong number of scores is a
        broken answer, not an unavailable service, and it must still fail (§7).

        Returns:
            One score per candidate, in the candidates' order, or ``None`` when the re-ranking
            service is unavailable, which tells the caller to keep the RRF order (P2-19).

        Raises:
            ServiceError: The service answered with a different number of scores than there were
                candidates, which would pair scores with the wrong chunks.
        """
        try:
            scores = self.models.rerank(query, [chunk.text for chunk in candidates])  # P6
        except ServiceError:
            # No query or chunk text in the warning (P2-29).
            logger.warning(
                "re-ranker unavailable, keeping the RRF order", extra={"stage": "rerank"}
            )
            return None
        if len(scores) != len(candidates):
            raise ServiceError("re-ranking service returned an unexpected number of scores")
        return [float(score) for score in scores]

    # --- Indexing and rights: the store owns every write (§3.2, §3.5) -------------------------

    def index(self, chunks: list[Chunk]) -> None:
        """Embeds and stores the chunks of one document, hidden (P2-05…P2-10)."""
        self.store.index(chunks)

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        """Sets ``allowed_roles`` on every chunk of the document; ``hidden`` is unchanged."""
        self.store.update_roles(doc_id, roles)

    def hide(self, doc_id: str) -> None:
        """Sets ``hidden = True`` on every chunk of the document (P2-24)."""
        self.store.hide(doc_id)

    def show(self, doc_id: str) -> None:
        """Sets ``hidden = False`` on every chunk of the document (P2-24)."""
        self.store.show(doc_id)

    def delete(self, doc_id: str) -> None:
        """Deletes every chunk of the document (P2-25)."""
        self.store.delete(doc_id)
