"""In-memory fake of the ``LeakIndex`` Protocol (00-shared §6.4, §9; P6 spec §3.6).

The real P6 hashes every 4-gram of a document with HMAC inside ``api`` and stores only the hashes
in ``web-search`` (SQLite). This fake keeps the normalized 4-grams themselves in memory, with no
HMAC and no HTTP (00-shared §9: "in-memory sets of 4-grams, no HMAC"), so P1 and P5 can call
``register``, ``set_blocking`` and ``delete`` before ``web-search`` exists.

``hits`` is not part of the Protocol. It applies the hit rule of the real filter (P6-33) to a
query, so tests can check what the index holds. Document references (P6-30) and ``leak.max_df``
are left out of the fake.

Log lines never contain document text or query text (P6 spec §7).
"""

import logging

from src.ingestion.normalize import normalize_ar

logger = logging.getLogger(__name__)

DEFAULT_NGRAM = 4  # leak.ngram


def ngrams(text: str, n: int = DEFAULT_NGRAM) -> set[str]:
    """Every run of ``n`` consecutive words of the normalized text, as one string each.

    The same tokens the real fingerprints use (P6-29): ``normalize_ar(text).split()``. A text
    shorter than ``n`` words has no n-gram.
    """
    tokens = normalize_ar(text).split()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


class FakeLeakIndex:
    """``LeakIndex`` kept in memory, with plain n-grams instead of HMAC fingerprints.

    Args:
        ngram: Words per n-gram (``leak.ngram``).

    Raises:
        ValueError: ``ngram`` below 1.
    """

    def __init__(self, *, ngram: int = DEFAULT_NGRAM) -> None:
        if ngram < 1:
            raise ValueError("ngram must be at least 1")
        self.ngram = ngram
        self._grams: dict[str, set[str]] = {}  # doc_id -> its n-grams
        self._blocking: dict[str, bool] = {}  # doc_id -> blocking flag

    def register(self, doc_id: str, text: str) -> None:
        """Stores the document's n-grams, blocking (P6-31).

        Registering the same ``doc_id`` again replaces its n-grams and makes it blocking again,
        so calling it twice with the same text leaves the same state (idempotent).
        """
        self._grams[doc_id] = ngrams(text, self.ngram)
        self._blocking[doc_id] = True
        logger.info("document registered", extra={"doc_id": doc_id})

    def set_blocking(self, doc_id: str, blocking: bool) -> None:
        """Sets whether the document's n-grams can block a query (P6-31). Idempotent.

        An unknown ``doc_id`` changes nothing and only logs a warning.
        """
        if doc_id not in self._blocking:
            logger.warning("unknown document", extra={"action": "set_blocking", "doc_id": doc_id})
            return
        self._blocking[doc_id] = blocking

    def delete(self, doc_id: str) -> None:
        """Removes the document's n-grams (P6-31). Idempotent; an unknown ``doc_id`` is ignored."""
        self._grams.pop(doc_id, None)
        self._blocking.pop(doc_id, None)

    def hits(self, query: str) -> int:
        """Number of the query's n-grams that count as hits (P6-33). Not part of the Protocol.

        An n-gram is a hit when at least one blocking document contains it and no non-blocking
        (public) document does: a phrase also found in public law never blocks.
        """
        count = 0
        for gram in ngrams(query, self.ngram):
            owners = [self._blocking[d] for d, grams in self._grams.items() if gram in grams]
            if owners and all(owners):
                count += 1
        return count
