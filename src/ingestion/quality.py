"""Page text quality assessment module for P1 (Ingestion).

Implements digital text verification and heuristics to detect scanned,
corrupted, or visual-order reversed Arabic text (P1-08, §6.2).
"""

from __future__ import annotations

import re

# Arabic Presentation Forms-A and Forms-B
PRESENTATION_FORMS: list[tuple[int, int]] = [
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
]

# Frequent words in Moroccan legal corpus (§6.2)
FREQUENT_WORDS: frozenset[str] = frozenset(
    {
        "المادة",
        "الفصل",
        "الباب",
        "الكتاب",
        "القسم",
        "الفرع",
        "على",
        "في",
        "من",
        "إلى",
        "عن",
        "أن",
        "إن",
        "التي",
        "الذي",
        "الذين",
        "هذا",
        "هذه",
        "ذلك",
        "قانون",
        "مرسوم",
        "ظهير",
        "رقم",
        "المملكة",
        "المغربية",
        "الجريدة",
        "الرسمية",
        "حيث",
        "بما",
        "كل",
        "أو",
        "مع",
        "بين",
        "بعد",
        "قبل",
        "عند",
        "لدى",
    }
)


def share_in_ranges(text: str, ranges: list[tuple[int, int]]) -> float:
    """Compute proportion of non-whitespace characters falling in given Unicode ranges."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    matching = sum(1 for c in chars if any(start <= ord(c) <= end for start, end in ranges))
    return matching / len(chars)


def share_of_reversed_words(text: str) -> float:
    """Compute proportion of words whose reverse is a frequent word (§6.2).

    Calculates the proportion of words whose reverse matches a known frequent legal
    word while the word itself is not in that list.
    """
    words = [re.sub(r"[^\w]", "", w) for w in text.split()]
    words = [w for w in words if w]
    if not words:
        return 0.0

    candidates = [w for w in words if w in FREQUENT_WORDS or w[::-1] in FREQUENT_WORDS]
    if not candidates:
        return 0.0

    reversed_count = sum(
        1 for w in candidates if w not in FREQUENT_WORDS and w[::-1] in FREQUENT_WORDS
    )
    return reversed_count / len(candidates)


def passes_quality_check(text: str, min_letters: int = 50) -> bool:
    """Check whether extracted page text passes quality standards (P1-08, §6.2).

    Args:
        text: Page text after NFKC normalization.
        min_letters: Minimum alphabetic characters required (from config).

    Returns:
        True if text is suitable for digital extraction; False if page requires OCR.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < min_letters:
        return False
    if share_in_ranges(text, PRESENTATION_FORMS) > 0.05:
        return False
    if share_of_reversed_words(text) > 0.3:
        return False
    return True
