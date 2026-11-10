"""Arabic text normalization module for P1 (Ingestion).

Implements the 11 sequential normalization rules specified in P1-15.
Shared across P1 (chunks), P2 (queries, BM25), P3 (reformulations),
P4 (excerpt check), and P6 (fingerprints).
"""

from __future__ import annotations

import re
import unicodedata

# Rule 2: Remove invisible format characters (Unicode category Cf)
# e.g. RLM (U+200F), LRM (U+200E), ZWNJ (U+200C), ZWJ (U+200D), BOM (U+FEFF), ALM (U+061C), SHY (U+00AD)
_CF_TRANSLATE = {
    code_point: None
    for code_point in range(0x110000)
    if unicodedata.category(chr(code_point)) == "Cf"
}

# Rule 3: Remove diacritics U+064B–U+065F (harakat, shadda, sukun, etc.) and U+0670 (dagger alef)
_DIACRITICS_RE = re.compile(r"[\u064b-\u065f\u0670]")

# Rule 5: Normalize alef variants (أ, إ, آ, ٱ -> ا)
_ALEF_RE = re.compile(r"[أإآٱ]")

# Rule 8: Convert Arabic-Indic (٠-٩) and Persian (۰-۹) digits to ASCII (0-9)
_DIGIT_TRANSLATE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

# Rule 10: Precomputed translation table for all punctuation (P*) and symbol (S*) characters
_PUNCT_SYMBOL_TRANSLATE = {
    code_point: " "
    for code_point in range(0x110000)
    if unicodedata.category(chr(code_point))[0] in ("P", "S")
}


def normalize_ar(text: str) -> str:
    """Normalize Arabic text according to the 11 rules of P1-15.

    Rules applied in this exact order:
    1. Unicode NFKC (presentation forms -> base letters).
    2. Remove invisible format characters (Unicode category Cf).
    3. Remove diacritics U+064B–U+065F and U+0670.
    4. Remove tatweel U+0640.
    5. Normalize alef variants (أ, إ, آ, ٱ -> ا).
    6. Convert alif maqsura to yeh (ى -> ي).
    7. Convert teh marbuta to heh (ة -> ه).
    8. Convert Arabic-Indic (٠–٩) and Persian (۰–۹) digits to 0–9.
    9. Lowercase Latin letters.
    10. Replace all punctuation and symbols (Unicode categories P* and S*) with a space.
    11. Collapse whitespace and strip.

    No stemming is performed (P1-16).
    The operation is strictly idempotent: normalize_ar(normalize_ar(x)) == normalize_ar(x) (P1-17).

    Args:
        text: Input string to normalize.

    Returns:
        Normalized, whitespace-collapsed, stripped string.
    """
    if not text:
        return ""

    # Rule 1: Unicode NFKC
    text = unicodedata.normalize("NFKC", text)

    # Rule 2: Remove invisible format characters (Unicode category Cf)
    text = text.translate(_CF_TRANSLATE)

    # Rule 3: Remove diacritics
    text = _DIACRITICS_RE.sub("", text)

    # Rule 4: Remove tatweel
    text = text.replace("\u0640", "")

    # Rule 5: Map alef forms to bare alef
    text = _ALEF_RE.sub("ا", text)

    # Rule 6: ى -> ي
    text = text.replace("ى", "ي")

    # Rule 7: ة -> ه
    text = text.replace("ة", "ه")

    # Rule 8: Digits -> 0-9
    text = text.translate(_DIGIT_TRANSLATE)

    # Rule 9: Lowercase Latin
    text = text.lower()

    # Rule 10: Replace punctuation and symbols with spaces
    text = text.translate(_PUNCT_SYMBOL_TRANSLATE)

    # Rule 11: Collapse whitespace and strip
    return " ".join(text.split())
