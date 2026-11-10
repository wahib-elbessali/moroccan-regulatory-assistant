"""Qdrant storage and access control (P2 spec §3.1, §3.2, §3.5, §6.1, §6.3, §6.7).

Qdrant is the only store of chunks. Every point is one chunk: ID = chunk_id, payload = every
field of the Chunk + ``hidden``. The visibility rule (00-shared §6.3) is always applied inside
the Qdrant query, never on the results.

Log lines and error messages never contain query text, chunk text or document titles.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from qdrant_client import QdrantClient, models

from src.core.contracts import (
    AppError,
    Chunk,
    InvalidInput,
    ModelsClient,
    ServiceError,
    UserContext,
    make_chunk_id,
)

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1024  # bge-m3
HEADING_SEPARATOR = " › "

# Payload fields used in filters (P2-03).
INDEXED_FIELDS: dict[str, models.PayloadSchemaType] = {
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "allowed_roles": models.PayloadSchemaType.KEYWORD,
    "owner_id": models.PayloadSchemaType.KEYWORD,
    "hidden": models.PayloadSchemaType.BOOL,
}

_SCROLL_PAGE = 256


def embedding_text(chunk: Chunk) -> str:
    """Builds the text that is embedded for a chunk (P2-07).

    Title, then the headings (``hierarchy`` + ``article``) joined with `` › ``, then the text,
    one per line. Empty parts are skipped.

    Args:
        chunk: The chunk to embed.

    Returns:
        For example ``"القانون رقم 31.08\\nالباب الثاني › المادة 12\\n<text>"``.
    """
    headings = HEADING_SEPARATOR.join(chunk.hierarchy + ([chunk.article] if chunk.article else []))
    return "\n".join(part for part in (chunk.title, headings, chunk.text) if part)


def visibility_filter(ctx: UserContext) -> models.Filter:
    """The visibility rule of 00-shared §6.3, as a Qdrant filter (P2-12).

    ``not hidden AND (owner_id == ctx.user_id OR ctx.role in allowed_roles)``.
    ``allowed_roles`` is a list: ``MatchValue`` matches when the list contains the value.

    Args:
        ctx: The user's context. Required.

    Raises:
        InvalidInput: If ``ctx`` is None.
    """
    if ctx is None:
        raise InvalidInput("user context required")
    return models.Filter(
        must=[models.FieldCondition(key="hidden", match=models.MatchValue(value=False))],
        should=[  # at least one must match
            models.FieldCondition(key="owner_id", match=models.MatchValue(value=str(ctx.user_id))),
            models.FieldCondition(key="allowed_roles", match=models.MatchValue(value=ctx.role)),
        ],
    )


def validate_chunks(chunks: list[Chunk]) -> None:
    """Checks a list of chunks before indexing (P2-05).

    Raises:
        InvalidInput: Empty list, more than one ``doc_id``, a ``chunk_id`` that is not
            ``make_chunk_id(doc_id, chunk_index)``, different ``total_chunks`` values, or a
            ``chunk_index`` outside ``0 … total_chunks - 1``.
    """
    if not chunks:
        raise InvalidInput("no chunks to index")
    doc_id, total = chunks[0].doc_id, chunks[0].total_chunks
    for c in chunks:
        if c.doc_id != doc_id:
            raise InvalidInput("chunks from more than one document")
        if c.total_chunks != total:
            raise InvalidInput("total_chunks differs between chunks")
        if not 0 <= c.chunk_index < total:
            raise InvalidInput("chunk_index out of range")
        if c.chunk_id != make_chunk_id(doc_id, c.chunk_index):
            raise InvalidInput("chunk_id does not match doc_id and chunk_index")


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
    )


def _to_chunk(payload: dict[str, Any] | None) -> Chunk:
    data = {k: v for k, v in (payload or {}).items() if k != "hidden"}
    return Chunk.model_validate(data)


@contextmanager
def _qdrant_errors(action: str) -> Iterator[None]:
    """Turns any Qdrant failure into ServiceError, with a message that holds no content."""
    try:
        yield
    except AppError:
        raise
    except Exception as exc:
        logger.error("qdrant call failed", extra={"action": action, "error": type(exc).__name__})
        raise ServiceError(f"qdrant unavailable ({action})") from exc


class QdrantStore:
    """Everything P2 does in Qdrant: storage, search with the visibility filter, rights.

    Args:
        client: A Qdrant client (``QdrantClient(url=...)``, or ``QdrantClient(":memory:")`` in
            tests).
        models_client: Where embeddings come from (``get_models()``). P2 never loads a model.
        collection: Collection name (``retrieval.collection``).
        embed_batch_size: Texts per ``embed`` call (``retrieval.embed_batch_size``).
        on_write: Called after every write (index, delete, update_roles, hide, show), so BM25
            knows it must rebuild (§6.5). The real factory passes ``bump_version``.
    """

    def __init__(
        self,
        client: QdrantClient,
        models_client: ModelsClient,
        *,
        collection: str = "chunks",
        embed_batch_size: int = 32,
        on_write: Callable[[], None] = lambda: None,
    ) -> None:
        if embed_batch_size < 1:
            raise ValueError("embed_batch_size must be at least 1")
        self.client = client
        self.models = models_client
        self.collection = collection
        self.embed_batch_size = embed_batch_size
        self.on_write = on_write

    # --- Storage (§3.1, §3.2) ----------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Creates the collection and its payload indexes if missing (P2-01, P2-03).

        Raises:
            ServiceError: Qdrant unreachable.
        """
        with _qdrant_errors("ensure_collection"):
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(
                        size=VECTOR_SIZE, distance=models.Distance.COSINE
                    ),
                )
                logger.info("collection created", extra={"collection": self.collection})
            for field, schema in INDEXED_FIELDS.items():
                self.client.create_payload_index(self.collection, field, field_schema=schema)

    def index(self, chunks: list[Chunk]) -> None:
        """Embeds and stores the chunks of one document, hidden (P2-05…P2-10).

        Re-indexing the same ``chunk_id`` overwrites it. Afterwards, any chunk of that document
        with ``chunk_index >= total_chunks`` (left over from an older, longer version) is
        deleted.

        Args:
            chunks: All chunks of one document, from P1, with ``allowed_roles`` as received.

        Raises:
            InvalidInput: The list is invalid (see ``validate_chunks``); nothing is written.
            ServiceError: Embedding or Qdrant failed.
        """
        validate_chunks(chunks)
        doc_id, total = chunks[0].doc_id, chunks[0].total_chunks
        vectors = self._embed([embedding_text(c) for c in chunks])
        points = [
            models.PointStruct(
                id=c.chunk_id,
                vector=v,
                payload={**c.model_dump(mode="json"), "hidden": True},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        leftovers = models.Filter(
            must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="chunk_index", range=models.Range(gte=total)),
            ]
        )
        with _qdrant_errors("index"):
            self.client.upsert(self.collection, points=points, wait=True)
            self.client.delete(
                self.collection, points_selector=models.FilterSelector(filter=leftovers), wait=True
            )
        self.on_write()
        logger.info("document indexed", extra={"doc_id": doc_id, "chunks": len(chunks)})

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.embed_batch_size):
            batch = texts[start : start + self.embed_batch_size]
            vectors += self.models.embed(batch)  # P6; raises ServiceError
        if len(vectors) != len(texts) or any(len(v) != VECTOR_SIZE for v in vectors):
            raise ServiceError("embedding service returned unexpected vectors")
        return vectors

    # --- Search (§3.3, §6.3) -----------------------------------------------------------------

    def vector_search(self, vector: list[float], flt: models.Filter, limit: int) -> list[Chunk]:
        """Nearest chunks to ``vector`` among those that pass ``flt``, best first (P2-12).

        The filter is part of the Qdrant query: a chunk that fails it is never scored.

        Args:
            vector: The query embedding.
            flt: ``visibility_filter(ctx)``.
            limit: Maximum number of chunks (``retrieval.top_k_vector``).

        Raises:
            ServiceError: Qdrant unreachable.
        """
        with _qdrant_errors("vector_search"):
            result = self.client.query_points(
                self.collection, query=vector, query_filter=flt, limit=limit, with_payload=True
            )
        return [_to_chunk(p.payload) for p in result.points]

    def recheck(self, chunk_ids: list[str], flt: models.Filter) -> dict[str, Chunk]:
        """Keeps only the chunk IDs that Qdrant returns with ``flt`` (P2-14).

        BM25 lives in memory and can be a moment behind Qdrant; this makes that harmless.

        Args:
            chunk_ids: Candidates from BM25.
            flt: ``visibility_filter(ctx)``, the same one used for the vector search.

        Returns:
            ``{chunk_id: Chunk}`` for the IDs that still pass the filter. Order is not kept.

        Raises:
            ServiceError: Qdrant unreachable.
        """
        if not chunk_ids:
            return {}
        both = models.Filter(must=[models.HasIdCondition(has_id=list(chunk_ids)), flt])
        with _qdrant_errors("recheck"):
            points, _ = self.client.scroll(
                self.collection,
                scroll_filter=both,
                limit=len(chunk_ids),
                with_payload=True,
                with_vectors=False,
            )
        return {str(p.id): _to_chunk(p.payload) for p in points}

    def scroll_payloads(self) -> list[dict[str, Any]]:
        """Every point's payload (``hidden`` included), without vectors. BM25 is rebuilt from
        these (P2-04, §6.5).

        Raises:
            ServiceError: Qdrant unreachable.
        """
        payloads: list[dict[str, Any]] = []
        offset: Any = None
        with _qdrant_errors("scroll_payloads"):
            while True:
                points, offset = self.client.scroll(
                    self.collection,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                payloads += [dict(p.payload or {}) for p in points]
                if offset is None:
                    return payloads

    # --- Rights and state (§3.5, §6.7) -------------------------------------------------------

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        """Sets ``allowed_roles`` on every chunk of the document; ``hidden`` is unchanged
        (P2-23). Idempotent; an unknown ``doc_id`` only logs a warning.

        Raises:
            ServiceError: Qdrant failed; the caller (P5) keeps the document hidden.
        """
        self._set_payload(doc_id, {"allowed_roles": list(roles)}, "update_roles")

    def hide(self, doc_id: str) -> None:
        """Sets ``hidden = True`` on every chunk of the document (P2-24)."""
        self._set_payload(doc_id, {"hidden": True}, "hide")

    def show(self, doc_id: str) -> None:
        """Sets ``hidden = False`` on every chunk of the document (P2-24)."""
        self._set_payload(doc_id, {"hidden": False}, "show")

    def delete(self, doc_id: str) -> None:
        """Deletes every chunk of the document (P2-25). Idempotent.

        Raises:
            ServiceError: Qdrant failed.
        """
        if not self._has_points(doc_id, "delete"):
            return
        with _qdrant_errors("delete"):
            self.client.delete(
                self.collection,
                points_selector=models.FilterSelector(filter=_doc_filter(doc_id)),
                wait=True,
            )
        self.on_write()

    def _set_payload(self, doc_id: str, payload: dict[str, Any], action: str) -> None:
        if not self._has_points(doc_id, action):
            return
        with _qdrant_errors(action):
            # One call over all points of the document (P2-27).
            self.client.set_payload(
                self.collection, payload=payload, points=_doc_filter(doc_id), wait=True
            )
        self.on_write()

    def _has_points(self, doc_id: str, action: str) -> bool:
        with _qdrant_errors(action):
            n = self.client.count(self.collection, count_filter=_doc_filter(doc_id), exact=True)
        if n.count == 0:
            logger.warning("no chunks for document", extra={"action": action, "doc_id": doc_id})
            return False
        return True
