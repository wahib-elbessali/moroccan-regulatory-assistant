"""Leak fingerprints: HMAC of every 4-gram and every reference of a text (P6-29, P6-30, P6-35).

``api`` turns each protected document into fingerprints before anything leaves it, so only
16-character hex strings ever reach ``web-search``. ``web-search`` runs the same function on every
outgoing query, so a query is hashed exactly like the documents and the two can be compared
without either side holding the text.

This module depends only on the standard library and P1's ``normalize_ar``, because the
``web-search`` image installs it on its own, without the rest of ``api``.

Never log the text passed in, the n-grams built from it, or the key.
"""

import hashlib
import hmac
import os
import re

from src.core.contracts.errors import ServiceError
from src.ingestion.normalize import normalize_ar

HMAC_KEY_ENV = "LEAK_HMAC_KEY"
DEFAULT_NGRAM = 4  # leak.ngram
FINGERPRINT_CHARS = 16
REF_PREFIX = "ref:"

# A document reference in normalized text: "رقم" or "عدد" followed by numbers. Normalization
# turns "١٢/٢٠٢٥" into "12 2025", so "دورية رقم ١٢/٢٠٢٥" gives "رقم 12 2025" (P6-30).
REF_PATTERN = re.compile(r"(رقم|عدد)((?: \d+)+)")


def load_hmac_key() -> bytes:
    """The shared HMAC key, from ``LEAK_HMAC_KEY`` in ``.env`` (P6-35).

    Raises:
        ServiceError: The variable is missing or empty. Without the key, ``api`` and
            ``web-search`` could not produce the same fingerprints.
    """
    key = os.environ.get(HMAC_KEY_ENV, "")
    if not key:
        raise ServiceError(f"{HMAC_KEY_ENV} is not set")
    return key.encode("utf-8")


def hmac16(key: bytes, value: str) -> str:
    """``HMAC-SHA256(key, value)``, first 16 hex characters (P6-29)."""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:FINGERPRINT_CHARS]


def ngrams(normalized: str, n: int = DEFAULT_NGRAM) -> set[str]:
    """Every run of ``n`` consecutive words of an already normalized text."""
    tokens = normalized.split()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def references(normalized: str) -> set[str]:
    """Every document reference of an already normalized text, with its ``ref:`` prefix."""
    return {REF_PREFIX + m.group(0) for m in REF_PATTERN.finditer(normalized)}


def fingerprints(text: str, key: bytes, n: int = DEFAULT_NGRAM) -> tuple[list[str], list[str]]:
    """The fingerprints of a text: its 4-grams and its references, each hashed (P6-29, P6-30).

    Args:
        text: A document's full text, or an outgoing web query.
        key: The shared HMAC key (``load_hmac_key``).
        n: Words per n-gram (``leak.ngram``).

    Returns:
        ``(grams, refs)``: two sorted lists of distinct 16-character hex strings. A text shorter
        than ``n`` words has no gram.
    """
    norm = normalize_ar(text)
    grams = sorted({hmac16(key, g) for g in ngrams(norm, n)})
    refs = sorted({hmac16(key, r) for r in references(norm)})
    return grams, refs
