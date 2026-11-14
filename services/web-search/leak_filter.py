"""Leak detection for outgoing web-search queries (P6-33, P6-34)."""

from __future__ import annotations

from src.core.leak.fingerprint import fingerprints
from src.ingestion.normalize import normalize_ar

from store import SQLiteLeakStore


class LeakFilter:
    """Detect protected document fingerprints in outgoing queries."""

    def __init__(
        self,
        store: SQLiteLeakStore,
        key: bytes,
        *,
        ngram: int = 4,
        min_hits: int = 3,
        max_df: int = 20,
        overlap_threshold: float = 0.2,
    ) -> None:
        if ngram < 1:
            raise ValueError("ngram must be at least 1")
        if min_hits < 1:
            raise ValueError("min_hits must be at least 1")
        if max_df < 1:
            raise ValueError("max_df must be at least 1")
        if not 0 <= overlap_threshold <= 1:
            raise ValueError("overlap_threshold must be between 0 and 1")

        self.store = store
        self.key = key
        self.ngram = ngram
        self.min_hits = min_hits
        self.max_df = max_df
        self.overlap_threshold = overlap_threshold

    def leak_hits(self, query: str) -> list[str]:
        """Return protected fingerprints matching the query."""
        grams, refs = fingerprints(query, self.key, self.ngram)
        hits: list[str] = []

        for fingerprint in grams + refs:
            entries = self.store.get(fingerprint)

            if not entries:
                continue

            # A fingerprint present in any public document is not protected.
            if any(not blocking for _, blocking, _ in entries):
                continue

            # max_df counts distinct documents, not database rows.
            document_ids = {doc_id for doc_id, _, _ in entries}
            if len(document_ids) >= self.max_df:
                continue

            if any(blocking for _, blocking, _ in entries):
                hits.append(fingerprint)

        return hits

    def is_blocked(self, hits: list[str], query: str) -> bool:
        """Apply the reference, absolute-hit and overlap blocking rules."""
        if not hits:
            return False

        _, refs = fingerprints(query, self.key, self.ngram)

        # A protected reference blocks immediately.
        if set(hits).intersection(refs):
            return True

        normalized_query = normalize_ar(query)
        n_grams = max(
            1,
            len(normalized_query.split()) - self.ngram + 1,
        )

        return (
            len(hits) >= self.min_hits
            or len(hits) / n_grams >= self.overlap_threshold
        )

    def check(self, query: str) -> tuple[bool, int]:
        """Return (blocked, hit_count) without logging query content."""
        hits = self.leak_hits(query)
        return self.is_blocked(hits, query), len(hits)
