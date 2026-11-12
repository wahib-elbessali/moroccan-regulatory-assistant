"""Article-based and fixed-size document chunking engine for P1 (Ingestion) (P1-18 à P1-26, §6.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.contracts.ids import make_chunk_id
from src.core.contracts.lang import detect_language
from src.core.contracts.models import Chunk, DocumentMeta
from src.ingestion.extract import _read_config
from src.ingestion.models import Page
from src.ingestion.normalize import normalize_ar
from src.ingestion.ordinals import (
    HEADING_EOL_RE,
    HEADING_START_RE,
    ISOLATED_LEVEL_WORDS,
    LEVELS,
    NEXT_POSTPOSITIONS,
    NUM_OR_ORD_RE,
    PREV_PREPOSITIONS,
    canonical_heading_label,
    normalize_level_word,
)


@dataclass
class _HeadingMatch:
    word: str
    label: str
    is_article: bool
    title_extra: str | None = None


@dataclass
class _ChunkUnit:
    article: str | None
    hierarchy: list[str]
    lines: list[tuple[int, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line for _, line in self.lines).strip()

    @property
    def first_page(self) -> int:
        if not self.lines:
            return 1
        return min(p for p, _ in self.lines)

    @property
    def last_page(self) -> int:
        if not self.lines:
            return 1
        return max(p for p, _ in self.lines)

    def add(self, line: str, page_no: int) -> None:
        self.lines.append((page_no, line))


def heading_word(heading: str) -> str:
    """Extract the primary level word from a heading string."""
    parts = heading.strip().split()
    if not parts:
        return ""
    first = parts[0]
    return normalize_level_word(first)


def update_path(path: list[str], word: str, heading: str) -> list[str]:
    """Update hierarchy path by keeping only higher levels and appending heading (§6.3, T21)."""
    norm_word = normalize_level_word(word)
    if norm_word not in LEVELS:
        return list(path) + [heading]

    level = LEVELS.index(norm_word)
    kept: list[str] = []
    for p in path:
        w = normalize_level_word(heading_word(p))
        if w in LEVELS and LEVELS.index(w) < level:
            kept.append(p)
    return kept + [heading]


def _is_cross_reference_citation(
    lines: list[tuple[int, str]],
    current_idx: int,
    heading_match: re.Match[str],
) -> bool:
    """Detect whether a matched heading pattern is actually a citation in body text."""
    # Check if preceding text ends with a citation preposition
    if current_idx > 0:
        prev_line = lines[current_idx - 1][1].strip()
        if any(prev_line.endswith(prep) for prep in PREV_PREPOSITIONS):
            return True

    # Check if the line itself has citation prepositions before the match
    line = lines[current_idx][1]
    prefix = line[: heading_match.start()].strip()
    if prefix and any(prefix.endswith(prep) for prep in PREV_PREPOSITIONS):
        return True

    # Check if following text starts with a cross-reference postposition
    remainder = line[heading_match.end() :].lstrip(" \t:：-–.")
    if any(remainder.startswith(post) for post in NEXT_POSTPOSITIONS):
        return True

    if current_idx + 1 < len(lines):
        next_line = lines[current_idx + 1][1].lstrip(" \t:：-–.")
        if any(next_line.startswith(post) for post in NEXT_POSTPOSITIONS):
            return True

    return False


def _match_heading(
    lines: list[tuple[int, str]],
    idx: int,
) -> _HeadingMatch | None:
    """Match heading pattern at current line, supporting start-of-line and EOL formats."""
    line = lines[idx][1].strip()
    if not line:
        return None

    # Format 1: Heading at start of line
    m_start = HEADING_START_RE.match(line)
    if m_start:
        if _is_cross_reference_citation(lines, idx, m_start):
            return None
        word = normalize_level_word(m_start.group(1))
        num_ord = m_start.group(2)
        suffix = m_start.group(3) if len(m_start.groups()) >= 3 else None
        canonical = canonical_heading_label(m_start.group(1), num_ord, suffix)

        remainder = line[m_start.end() :].strip().lstrip(" \t:：-–.")
        hier_label = f"{canonical}: {remainder}" if remainder else canonical
        is_art = word == "المادة"
        return _HeadingMatch(
            word=word,
            label=canonical,
            is_article=is_art,
            title_extra=hier_label,
        )

    # Format 2: Inverted EOL heading (e.g. internal documents: 'موضوع القانون ونطاق تطبيقه- 1 المادة')
    m_eol = HEADING_EOL_RE.match(line)
    if m_eol:
        title_extra = m_eol.group(1).strip()
        num = m_eol.group(2).strip()
        word = normalize_level_word(m_eol.group(3))
        canonical = canonical_heading_label(word, num)
        is_art = word == "المادة"
        return _HeadingMatch(
            word=word,
            label=canonical,
            is_article=is_art,
            title_extra=title_extra or None,
        )

    return None


def _fuse_isolated_headings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Fuse isolated heading word lines with following number lines (e.g. adala_001 P57/P102)."""
    fused: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        p_no, line = lines[i]
        sline = line.strip()
        if sline in ISOLATED_LEVEL_WORDS:
            # Look ahead for next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j][1].strip():
                j += 1
            if j < len(lines):
                next_p, next_l = lines[j]
                m = NUM_OR_ORD_RE.match(next_l.strip())
                if m:
                    num_val = m.group(1).strip()
                    suf_val = m.group(2).strip() if m.group(2) else None
                    fused_heading = canonical_heading_label(sline, num_val, suf_val)
                    fused.append((p_no, fused_heading))
                    remainder = next_l.strip()[m.end() :].lstrip(" \t:：-–.")
                    if remainder:
                        lines[j] = (next_p, remainder)
                        i = j
                    else:
                        i = j + 1
                    continue
        fused.append((p_no, line))
        i += 1
    return fused


def _split_long_line(page_no: int, line: str, max_chars: int) -> list[tuple[int, str]]:
    """Word-wrap a single long line exceeding max_chars."""
    if len(line) <= max_chars:
        return [(page_no, line)]
    words = line.split(" ")
    parts: list[str] = []
    cur_words: list[str] = []
    cur_len = 0
    for w in words:
        w_len = len(w)
        needed = w_len if not cur_words else (1 + w_len)
        if cur_words and (cur_len + needed > max_chars):
            parts.append(" ".join(cur_words))
            cur_words = [w]
            cur_len = w_len
        else:
            cur_words.append(w)
            cur_len += needed
    if cur_words:
        parts.append(" ".join(cur_words))
    return [(page_no, p) for p in parts if p.strip()]


def split_long(units: list[_ChunkUnit], max_chunk_chars: int) -> list[_ChunkUnit]:
    """Split units longer than max_chunk_chars at paragraph boundaries (P1-22, T4)."""
    result: list[_ChunkUnit] = []
    for u in units:
        if len(u.text) <= max_chunk_chars:
            result.append(u)
            continue

        expanded_lines: list[tuple[int, str]] = []
        for p_no, line_txt in u.lines:
            if len(line_txt) > max_chunk_chars:
                expanded_lines.extend(_split_long_line(p_no, line_txt, max_chunk_chars))
            else:
                expanded_lines.append((p_no, line_txt))

        current_lines: list[tuple[int, str]] = []
        current_len = 0

        for p_no, line_txt in expanded_lines:
            l_len = len(line_txt)
            needed = l_len if not current_lines else (1 + l_len)
            if current_lines and (current_len + needed > max_chunk_chars):
                sub_u = _ChunkUnit(
                    article=u.article,
                    hierarchy=list(u.hierarchy),
                    lines=list(current_lines),
                )
                result.append(sub_u)
                current_lines = [(p_no, line_txt)]
                current_len = l_len
            else:
                current_lines.append((p_no, line_txt))
                current_len += needed

        if current_lines:
            sub_u = _ChunkUnit(
                article=u.article,
                hierarchy=list(u.hierarchy),
                lines=list(current_lines),
            )
            result.append(sub_u)

    return result


def pack_paragraphs(
    lines: list[tuple[int, str, str | None, list[str]]],
    max_chunk_chars: int,
    overlap_chars: int,
) -> list[_ChunkUnit]:
    """Pack lines/paragraphs with sliding overlap (P1-23, P1-23b, T23)."""
    if not lines:
        return []

    # Filter empty lines
    non_empty: list[tuple[int, str, str | None, list[str]]] = [
        (p, line_str.strip(), art, hier) for p, line_str, art, hier in lines if line_str.strip()
    ]
    if not non_empty:
        return []

    # Word-wrap any line individually longer than max_chunk_chars
    clean_lines: list[tuple[int, str, str | None, list[str]]] = []
    for p, line_str, art, hier in non_empty:
        if len(line_str) > max_chunk_chars:
            sub = _split_long_line(p, line_str, max_chunk_chars)
            for sub_p, sub_l in sub:
                clean_lines.append((sub_p, sub_l, art, hier))
        else:
            clean_lines.append((p, line_str, art, hier))

    chunks: list[_ChunkUnit] = []
    idx = 0
    n = len(clean_lines)

    while idx < n:
        chunk_lines: list[tuple[int, str]] = []
        chunk_len = 0
        chunk_article = clean_lines[idx][2]
        chunk_hier = clean_lines[idx][3]
        last_idx = idx

        while last_idx < n:
            p_no, line_txt, _, _ = clean_lines[last_idx]
            needed = len(line_txt) if not chunk_lines else (1 + len(line_txt))
            if chunk_lines and (chunk_len + needed > max_chunk_chars):
                break
            chunk_lines.append((p_no, line_txt))
            chunk_len += needed
            last_idx += 1

        if chunk_lines:
            chunks.append(
                _ChunkUnit(
                    article=chunk_article,
                    hierarchy=list(chunk_hier),
                    lines=chunk_lines,
                )
            )

        if last_idx >= n:
            break

        # Compute next start index based on overlap_chars
        overlap_accum = 0
        back_idx = last_idx - 1
        while back_idx > idx:
            overlap_accum += len(clean_lines[back_idx][1]) + 1
            if overlap_accum >= overlap_chars:
                break
            back_idx -= 1

        # Prevent infinite loops: always advance at least 1 index past current idx
        idx = max(back_idx, idx + 1)

    return chunks


def _is_trivial_unit(u: _ChunkUnit) -> bool:
    """Return True if unit has fewer than 3 alphabetic letters or is purely punctuation/symbols."""
    letters = [c for c in u.text if c.isalpha()]
    return len(letters) < 3


def _clean_trivial_units(units: list[_ChunkUnit]) -> list[_ChunkUnit]:
    """Merge trivial units into subsequent units, or drop if isolated."""
    if not units:
        return []

    cleaned: list[_ChunkUnit] = []
    pending_lines: list[tuple[int, str]] = []

    for u in units:
        if _is_trivial_unit(u):
            pending_lines.extend(u.lines)
        else:
            if pending_lines:
                u.lines = pending_lines + u.lines
                pending_lines = []
            cleaned.append(u)

    if pending_lines and cleaned:
        cleaned[-1].lines.extend(pending_lines)

    return cleaned


def chunk_document(
    doc_id: str,
    pages: list[Page],
    owner_id: UUID | None = None,
    meta: DocumentMeta | None = None,
    strategy: str | None = None,
    max_chunk_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[Chunk]:
    """Chunk document pages into faithful, citable Chunk objects (P1-18 à P1-26, §6.3).

    Args:
        doc_id: Unique document identifier.
        pages: List of extracted Page objects.
        owner_id: Optional user UUID for private uploads.
        meta: Optional document metadata (title, source_file, source, date).
        strategy: 'article' (default) or 'fixed' (reads config if None).
        max_chunk_chars: Maximum chunk character length (reads config if None).
        overlap_chars: Overlap character length for sliding windows (reads config if None).

    Returns:
        List of structured Chunk objects.
    """
    if meta is None:
        meta = DocumentMeta(title="", source_file="")

    if strategy is None or max_chunk_chars is None or overlap_chars is None:
        cfg = _read_config()
        ing_cfg: dict[str, Any] = cfg.get("ingestion", {}) if isinstance(cfg, dict) else {}
        if strategy is None:
            strategy = str(ing_cfg.get("strategy", "article"))
        if max_chunk_chars is None:
            max_chunk_chars = int(ing_cfg.get("max_chunk_chars", 2000))
        if overlap_chars is None:
            overlap_chars = int(ing_cfg.get("overlap_chars", 200))

    raw_lines: list[tuple[int, str]] = [
        (page.number, line) for page in pages for line in page.text.splitlines()
    ]
    lines = _fuse_isolated_headings(raw_lines)

    # Determine article unit word: 'المادة' if any 'المادة' exists, otherwise 'الفصل' (P1-19)
    has_madda = False
    for i in range(len(lines)):
        hm = _match_heading(lines, i)
        if hm and hm.word == "المادة":
            has_madda = True
            break
    article_word = "المادة" if has_madda else "الفصل"

    if strategy == "fixed":
        # Strategy 'fixed' (P1-23b, T23): sliding window over all content
        annotated: list[tuple[int, str, str | None, list[str]]] = []
        cur_art: str | None = None
        cur_hier: list[str] = []
        for i in range(len(lines)):
            p_no, line_txt = lines[i]
            hm = _match_heading(lines, i)
            if hm and hm.word == article_word:
                cur_art = hm.label
            elif hm:
                cur_hier = update_path(cur_hier, hm.word, hm.title_extra or hm.label)
            annotated.append((p_no, line_txt, cur_art, list(cur_hier)))

        units = pack_paragraphs(annotated, max_chunk_chars, overlap_chars)
    else:
        # Strategy 'article' (P1-18 à P1-22, §6.3)
        units = []
        path: list[str] = []
        current = _ChunkUnit(article=None, hierarchy=[])

        for i in range(len(lines)):
            p_no, line_txt = lines[i]
            hm = _match_heading(lines, i)
            if hm and hm.word == article_word:
                units.append(current)
                current = _ChunkUnit(article=hm.label, hierarchy=list(path))
                current.add(line_txt, p_no)
            elif hm:
                path = update_path(path, hm.word, hm.title_extra or hm.label)
                continue
            else:
                current.add(line_txt, p_no)

        units.append(current)
        units = [u for u in units if u.text.strip()]

        if all(u.article is None for u in units):
            # Fallback when no articles found (P1-23)
            fallback_lines: list[tuple[int, str, str | None, list[str]]] = [
                (p, line_str, None, []) for u in units for p, line_str in u.lines
            ]
            units = pack_paragraphs(fallback_lines, max_chunk_chars, overlap_chars)
        else:
            units = split_long(units, max_chunk_chars)

    # Clean trivial chunks (< 3 letters / punctuation-only)
    units = _clean_trivial_units(units)

    total = len(units)
    return [
        Chunk(
            chunk_id=make_chunk_id(doc_id, i),
            doc_id=doc_id,
            chunk_index=i,
            total_chunks=total,
            text=u.text,
            text_normalized=normalize_ar(u.text),
            title=meta.title,
            article=u.article,
            hierarchy=u.hierarchy,
            page_start=u.first_page,
            page_end=u.last_page,
            language=detect_language(u.text),
            source_file=meta.source_file,
            source=meta.source,
            date=meta.date,
            allowed_roles=[],
            owner_id=owner_id,
        )
        for i, u in enumerate(units)
    ]
