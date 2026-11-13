"""Arabic PDF ligature correction module for digital PDF extraction (P1-07, P1-08, §6.2).

Detects and corrects visual-order ligature reversals in digital Arabic PDFs
(e.g., SakkalMajalla in SGG Bulletin Officiel, TimesNewRomanPSMT in Adala).
In these fonts, ligature components are emitted in visual sequence where leading
characters have zero bounding-box width (x1 - x0 < 0.01) and the final character
bears the glyph width. Inverting the letter order within such ligature groups
restores logical Arabic text (e.g., 'املادة' -> 'المادة', 'األولى' -> 'الأولى').
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pymupdf

logger = logging.getLogger(__name__)

# Pattern matching impossible Arabic ligature artifact sequences
IMPOSSIBLE_PATTERNS_RE: re.Pattern[str] = re.compile(r"ا[أإآ]ل|هللا|املادة", re.UNICODE)


def is_arabic_letter(c: str) -> bool:
    """Return True if c is a single Arabic alphabetic letter (excluding marks/digits)."""
    if len(c) != 1:
        return False
    # Must be a Letter (Lo, Ll, etc.) and NOT a Mark (Mn), Separator (Zs), or Number (Nd)
    if not unicodedata.category(c).startswith("L"):
        return False
    cp = ord(c)
    return (
        0x0621 <= cp <= 0x064A
        or 0x066E <= cp <= 0x06D3
        or 0x06D5 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0x08A0 <= cp <= 0x08FF
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
    )


def fix_span_ligatures(chars: list[tuple[str, float, float]]) -> str:
    """Pure function taking a list of (character, x0, x1) and returning corrected text.

    Rules:
      - A ligature group consists of zero-width Arabic letters (abs(x1 - x0) < 0.01)
        followed by the non-zero-width character that follows them.
      - Combining marks (Mn), spaces, digits, and punctuation are never accumulated
        as ligature components and maintain their exact relative positions.
      - If a group contains at least 2 Arabic letters, its order is reversed.
    """
    out: list[str] = []
    accum: list[str] = []

    for ch, x0, x1 in chars:
        w = abs(x1 - x0)
        # Only zero-width ARABIC LETTERS enter the ligature buffer
        if is_arabic_letter(ch) and w < 0.01:
            accum.append(ch)
        else:
            if accum:
                if is_arabic_letter(ch):
                    # Group = zero-width Arabic letters + terminating Arabic letter
                    group = accum + [ch]
                    out.extend(reversed(group))
                else:
                    # Trailing char is not an Arabic letter (space, punct, digit, mark)
                    out.extend(accum)
                    out.append(ch)
                accum = []
            else:
                out.append(ch)

    if accum:
        out.extend(accum)

    return "".join(out)


def repair_page_ligatures(page: pymupdf.Page) -> str:
    """Extract page text from rawdict and apply ligature correction to each span."""
    raw_dict = page.get_text("rawdict")
    lines_text: list[str] = []

    for b in raw_dict.get("blocks", []):
        if b.get("type", 0) != 0:  # Text block
            continue
        for line in b.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                span_chars = [(c["c"], c["bbox"][0], c["bbox"][2]) for c in span.get("chars", [])]
                line_parts.append(fix_span_ligatures(span_chars))
            lines_text.append("".join(line_parts))

    return "\n".join(lines_text)


def count_impossible_patterns(text: str) -> int:
    """Count occurrences of impossible Arabic ligature sequences."""
    return len(IMPOSSIBLE_PATTERNS_RE.findall(text))


def extract_digital_pdf_pages(
    doc: pymupdf.Document,
) -> tuple[list[str], str, dict[str, int]]:
    """Extract pages conditionally choosing between raw and corrected ligature variants.

    Computes raw text and ligature-corrected text across all pages.
    Selects corrected variant ONLY IF impossible patterns count is strictly lower
    AND the reduction is at least 3; otherwise preserves raw text.

    Returns:
        tuple of (selected_page_texts, variant_chosen, stats_dict)
    """
    raw_pages: list[str] = []
    corrected_pages: list[str] = []

    for i in range(len(doc)):
        page = doc[i]
        raw_pages.append(page.get_text())
        corrected_pages.append(repair_page_ligatures(page))

    full_raw = "\n".join(raw_pages)
    full_corrected = "\n".join(corrected_pages)

    raw_impossible = count_impossible_patterns(full_raw)
    corrected_impossible = count_impossible_patterns(full_corrected)

    diff = raw_impossible - corrected_impossible
    if corrected_impossible < raw_impossible and diff >= 3:
        variant = "corrected"
        chosen_pages = corrected_pages
    else:
        variant = "raw"
        chosen_pages = raw_pages

    stats = {
        "raw_impossible": raw_impossible,
        "corrected_impossible": corrected_impossible,
        "diff": diff,
    }
    logger.info(
        "Digital PDF ligature selection: variant=%s, raw_impossible=%d, corrected_impossible=%d",
        variant,
        raw_impossible,
        corrected_impossible,
    )

    return chosen_pages, variant, stats
