"""Shared helpers for P2 tests: deterministic models client, chunks and user contexts."""

import hashlib
import math
import uuid

from src.core.contracts import Chunk, UserContext, make_chunk_id, make_doc_id
from src.retrieval.store import VECTOR_SIZE


class HashModels:
    """Deterministic embeddings from a hash of each text; records the batch sizes it receives."""

    def __init__(self) -> None:
        self.embed_calls: list[int] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(len(texts))
        return [hash_vector(t) for t in texts]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        words = set(query.split())
        return [float(len(words & set(t.split()))) for t in texts]


def hash_vector(text: str) -> list[float]:
    raw: list[float] = []
    counter = 0
    while len(raw) < VECTOR_SIZE:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        raw += [b / 255 - 0.5 for b in digest]
        counter += 1
    raw = raw[:VECTOR_SIZE]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def make_doc(
    name: str,
    n: int = 2,
    *,
    roles: list[str] | None = None,
    owner_id: uuid.UUID | None = None,
    texts: list[str] | None = None,
    article: str | None = None,
) -> list[Chunk]:
    """All chunks of one document. ``name`` makes the doc_id unique."""
    doc_id = make_doc_id(name.encode(), owner_id)
    texts = texts or [f"نص {name} رقم {i}" for i in range(n)]
    return [
        Chunk(
            chunk_id=make_chunk_id(doc_id, i),
            doc_id=doc_id,
            chunk_index=i,
            total_chunks=len(texts),
            text=t,
            text_normalized=t,
            title=f"عنوان {name}",
            article=article,
            hierarchy=[],
            page_start=1,
            page_end=1,
            language="ar",
            source_file=f"{name}.pdf",
            source=None,
            date=None,
            allowed_roles=list(roles or []),
            owner_id=owner_id,
        )
        for i, t in enumerate(texts)
    ]


def make_ctx(role: str, user_id: uuid.UUID | None = None) -> UserContext:
    return UserContext(
        user_id=user_id or uuid.uuid4(),
        username=f"user-{role}",
        role=role,
        web_enabled=False,
        request_id=uuid.uuid4(),
    )
