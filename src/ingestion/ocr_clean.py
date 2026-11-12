"""OCR text cleaning and running header/footer removal (P1-11, P1-12, §6.2)."""

from __future__ import annotations

import re
import unicodedata

from .models import Page

HEADER_FOOTER_THRESHOLD: float = 0.50
HEADER_FOOTER_MIN_PAGES: int = 3
GROUP_MIN_PAGES: int = 2

INTERNAL_DOC_NOTICE: str = "وثيقة تجريبية — محتوى خيالي"

HEADING_PATTERN = re.compile(
    r"^\s*(الكتاب|الباب|القسم|الفرع|الفصل|المادة)\s+([0-9٠-٩]+|[^\s\d:]+)(\s+مكرر)?",
    re.UNICODE,
)

NUMBER_ONLY_PATTERN = re.compile(r"^\s*[-–—]?\s*[0-9٠-٩]+\s*[-–—]?\s*$")

DIGIT_WILDCARD_PATTERN = re.compile(r"[0-9٠-٩]+")


def clean_ocr(text: str) -> str:
    """Clean raw text produced by OCRClient (P1-11, §6.2).

    Applies Unicode NFKC normalization, removes control characters (except
    newlines and tabs), and normalizes line whitespace.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    cleaned_chars = [c for c in text if c in ("\n", "\t") or (unicodedata.category(c)[0] != "C")]
    cleaned = "".join(cleaned_chars)
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip()


def _mask_digits(line: str) -> str:
    """Replace sequences of digits with # so lines with variable numbers match."""
    return DIGIT_WILDCARD_PATTERN.sub("#", line.strip())


def _get_boundary_line_indices(lines: list[str]) -> set[int]:
    """Return indices of the first 2 and last 2 non-empty lines of a page."""
    non_empty = [i for i, line in enumerate(lines) if line.strip()]
    if not non_empty:
        return set()
    top_two = set(non_empty[:2])
    bottom_two = set(non_empty[-2:])
    return top_two | bottom_two


def remove_headers_footers(pages: list[Page]) -> list[Page]:
    """Remove repeating running headers, footers and page numbers (P1-12).

    Rules:
    1. Alternating and global headers/footers: A line in boundary positions (top 2
       or bottom 2 lines) is removed if its digit-masked template repeats across
       more than 50% of the entire document, or more than 50% of odd pages, or
       more than 50% of even pages (for documents with >= 3 pages and groups >= 2 pages).
    2. Number-only lines: Lines composed solely of a number are removed ONLY in
       boundary positions (first 2 or last 2 lines), preserving enumerations in body text.
    3. Headings protection: Lines matching legal headings (الكتاب, الباب, القسم, الفرع,
       الفصل, المادة) are NEVER removed.
    4. Internal document disclaimer: 'وثيقة تجريبية — محتوى خيالي' on page 1 is preserved once.
    """
    total_pages = len(pages)
    repeating_patterns: set[str] = set()

    if total_pages >= HEADER_FOOTER_MIN_PAGES:
        # Build groups: odd pages, even pages, and all pages
        odd_pages = [p for p in pages if p.number % 2 == 1]
        even_pages = [p for p in pages if p.number % 2 == 0]

        groups: list[list[Page]] = []
        if len(odd_pages) >= GROUP_MIN_PAGES:
            groups.append(odd_pages)
        if len(even_pages) >= GROUP_MIN_PAGES:
            groups.append(even_pages)
        groups.append(pages)

        for group in groups:
            group_size = len(group)
            pattern_pages: dict[str, set[int]] = {}
            for p in group:
                lines = p.text.splitlines()
                boundary_indices = _get_boundary_line_indices(lines)
                for idx in boundary_indices:
                    stripped = lines[idx].strip()
                    if not stripped or HEADING_PATTERN.match(stripped):
                        continue
                    if p.number == 1 and stripped == INTERNAL_DOC_NOTICE:
                        continue
                    masked = _mask_digits(stripped)
                    pattern_pages.setdefault(masked, set()).add(p.number)

            for pattern, page_set in pattern_pages.items():
                if len(page_set) / group_size > HEADER_FOOTER_THRESHOLD:
                    repeating_patterns.add(pattern)

    cleaned_pages: list[Page] = []
    for p in pages:
        lines = p.text.splitlines()
        boundary_indices = (
            _get_boundary_line_indices(lines)
            if total_pages >= HEADER_FOOTER_MIN_PAGES
            else _get_boundary_line_indices(lines)
        )
        kept_lines: list[str] = []

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                kept_lines.append("")
                continue

            # Rule 3: Heading lines are NEVER removed
            if HEADING_PATTERN.match(stripped):
                kept_lines.append(line)
                continue

            # Rule 4: Internal document notice preserved on page 1
            if p.number == 1 and stripped == INTERNAL_DOC_NOTICE:
                kept_lines.append(line)
                continue

            # Rule 2: Number-only lines removed ONLY in boundary positions
            if idx in boundary_indices and NUMBER_ONLY_PATTERN.match(stripped):
                continue

            # Rule 1: Repeating headers or footers in boundary positions
            if (
                total_pages >= HEADER_FOOTER_MIN_PAGES
                and idx in boundary_indices
                and _mask_digits(stripped) in repeating_patterns
            ):
                continue

            kept_lines.append(line)

        cleaned_text = "\n".join(kept_lines).strip()
        cleaned_pages.append(
            Page(
                number=p.number,
                text=cleaned_text,
                ocr=p.ocr,
                confidence=p.confidence,
            )
        )

    return cleaned_pages
