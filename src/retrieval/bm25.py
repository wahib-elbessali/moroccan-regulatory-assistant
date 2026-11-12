"""In-memory BM25 index with the visibility filter before scoring (P2 spec P2-04, P2-13, P2-21,
§6.4, §6.5, §7).

The index is rebuilt from Qdrant's payloads (``load_payloads``, which is
``QdrantStore.scroll_payloads`` in the real factory): P2 keeps no other copy of the chunks. Before
every search, the version file is read; the index is rebuilt only when its value has changed.

Only the chunks the user may see are scored. BM25 scores never leave this module: ``search``
returns chunk IDs only. Log lines never contain query tokens, chunk text or titles.

This module never imports ``store.py``: it only receives a function that returns payloads.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from src.core.contracts import InvalidInput, UserContext
from src.ingestion import normalize_ar

from .tokenizer import tokenize
from .version import bump_version, read_version

logger = logging.getLogger(__name__)


def bm25_text(payload: dict[str, Any]) -> str:
    """Builds the text that BM25 indexes for a chunk (P2-21).

    ``text_normalized`` is already normalized by P1; ``title`` and ``article`` are not, so they
    go through ``normalize_ar``. The article is included so that a query such as ``المادة 40``
    finds the chunk of that article (T18).

    Args:
        payload: A Qdrant payload (every field of the Chunk + ``hidden``).

    Returns:
        ``text_normalized``, the normalized title and the normalized article, joined by spaces.
    """
    return " ".join(
        [
            payload.get("text_normalized") or "",
            normalize_ar(payload.get("title") or ""),
            normalize_ar(payload.get("article") or ""),
        ]
    )


@dataclass(frozen=True)
class _Meta:
    """What the visibility rule needs for one chunk, at the same position as in the BM25 corpus."""

    chunk_id: str
    hidden: bool
    allowed_roles: frozenset[str]
    owner_id: str | None

    def visible_to(self, ctx: UserContext) -> bool:
        """The visibility rule of 00-shared §6.3, the same one as ``visibility_filter``."""
        return not self.hidden and (
            self.owner_id == str(ctx.user_id) or ctx.role in self.allowed_roles
        )


def _meta(payload: dict[str, Any]) -> _Meta:
    owner = payload.get("owner_id")
    return _Meta(
        chunk_id=str(payload["chunk_id"]),
        hidden=payload.get("hidden", True) is not False,  # missing or unexpected = hidden
        allowed_roles=frozenset(payload.get("allowed_roles") or ()),
        owner_id=str(owner) if owner is not None else None,
    )


@dataclass(frozen=True)
class _Snapshot:
    """One built index. Replaced as a whole, never changed, so concurrent searches always see
    metadata and scores that belong together."""

    version: str
    meta: tuple[_Meta, ...]
    bm25: Any  # BM25Okapi, or None when no chunk has any token (BM25Okapi cannot handle that)


class BM25Index:
    """BM25 over the chunks stored in Qdrant, rebuilt when the version file changes.

    Args:
        load_payloads: Returns every payload stored in Qdrant (``store.scroll_payloads``).
            Raises ``ServiceError`` when Qdrant is down; that error is passed on (§7: no
            fallback, the filter cannot be checked).
        version_file: The version file (``VERSION_FILE``), the same one ``QdrantStore``'s
            ``on_write`` bumps.
    """

    def __init__(self, load_payloads: Callable[[], list[dict[str, Any]]], version_file: Path):
        self._load_payloads = load_payloads
        self._version_file = version_file
        self._snap: _Snapshot | None = None
        self._lock = threading.Lock()

    def _current_version(self) -> str:
        """The version file's value. A missing file counts as a new version (§7): it is created,
        so the next searches compare against a real value instead of rebuilding every time."""
        value = read_version(self._version_file)
        if value is None:
            bump_version(self._version_file)
            value = read_version(self._version_file)
        return value or ""

    def refresh_if_stale(self) -> None:
        """Rebuilds the index from Qdrant if the version file changed since the last build (§6.5).

        The version is read **before** the payloads: a write that happens during the rebuild
        bumps the file again, so the next search rebuilds once more instead of missing it.

        Raises:
            ServiceError: The version file or Qdrant could not be read.
        """
        snap = self._snap
        if snap is not None and snap.version == self._current_version():
            return
        with self._lock:
            version = self._current_version()  # again: another search may have rebuilt
            snap = self._snap
            if snap is not None and snap.version == version:
                return
            start = time.perf_counter()
            payloads = self._load_payloads()
            meta = tuple(_meta(p) for p in payloads)
            corpus = [tokenize(bm25_text(p)) for p in payloads]
            bm25 = BM25Okapi(corpus) if any(corpus) else None
            self._snap = _Snapshot(version=version, meta=meta, bm25=bm25)  # one assignment
        logger.info(
            "bm25 index rebuilt",
            extra={"duration_ms": round((time.perf_counter() - start) * 1000)},
        )

    def search(self, tokens: list[str], ctx: UserContext, limit: int) -> list[str]:
        """The best visible chunks for the query tokens (P2-13, §6.4).

        The visibility rule picks the chunks first; only those are scored. Word statistics (IDF)
        come from the whole index.

        Args:
            tokens: ``tokenize(normalize_ar(query))``.
            ctx: The user's context. Required.
            limit: Maximum number of chunk IDs (``retrieval.top_k_bm25``).

        Returns:
            Chunk IDs, best first, only those with a score above 0. Equal scores are ordered by
            chunk ID. Empty if there are no tokens (e.g. only stopwords, T19) or no visible chunk.

        Raises:
            InvalidInput: ``ctx`` is None.
            ServiceError: The version file or Qdrant could not be read.
        """
        if ctx is None:
            raise InvalidInput("user context required")
        if not tokens or limit < 1:
            return []
        self.refresh_if_stale()
        snap = self._snap  # read once: a rebuild during this search does not mix two indexes
        if snap is None or snap.bm25 is None:
            return []
        visible = [i for i, m in enumerate(snap.meta) if m.visible_to(ctx)]  # BEFORE scoring
        if not visible:
            return []
        scores = snap.bm25.get_batch_scores(tokens, visible)
        ranked = sorted(
            zip(visible, scores, strict=True), key=lambda x: (-x[1], snap.meta[x[0]].chunk_id)
        )
        return [snap.meta[i].chunk_id for i, s in ranked[:limit] if s > 0]
