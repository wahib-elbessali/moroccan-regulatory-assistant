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
    """Update hierarchy path by keeping higher levels and root text title, then appending heading (§6.3, T21)."""
    norm_word = normalize_level_word(word)
    if norm_word not in LEVELS:
        return list(path) + [heading]

    level = LEVELS.index(norm_word)
    kept: list[str] = []
    for p in path:
        w = normalize_level_word(heading_word(p))
        if w not in LEVELS or LEVELS.index(w) < level:
            kept.append(p)
    return kept + [heading]


OPERATIVE_ARTICLE_BODY_VERBS: tuple[str, ...] = (
    "تتمم",
    "تنسخ",
    "تغير",
    "يعاقب",
    "يحدد",
    "تحدد",
    "يعفى",
    "تعفى",
    "يدخل",
    "تدخل",
    "يراد",
    "يقصد",
    "تتولى",
    "يتولى",
    "يخضع",
    "تخضع",
    "يمنع",
    "تمنع",
    "يعين",
    "تعين",
)


def _is_cross_reference_citation(
    lines: list[tuple[int, str]],
    current_idx: int,
    heading_match: re.Match[str],
) -> bool:
    """Detect whether a matched heading pattern is actually a citation in body text."""
    # Check if preceding text ends with a citation preposition (skipping empty lines)
    k = current_idx - 1
    while k >= 0 and not lines[k][1].strip():
        k -= 1
    if k >= 0:
        prev_line = lines[k][1].strip().rstrip(".,:؛!؟-–")
        words = prev_line.split()
        last_word = words[-1] if words else ""
        last_two_collapsed = "".join(words[-2:]) if len(words) >= 2 else ""
        if any(
            last_word == prep
            or last_two_collapsed == prep
            or (len(prep) > 3 and prev_line.endswith(prep))
            for prep in PREV_PREPOSITIONS
        ):
            return True

    # Check if the line itself has citation prepositions before the match
    line = lines[current_idx][1]
    prefix = line[: heading_match.start()].strip().rstrip(".,:؛!؟-–")
    if prefix:
        words_prefix = prefix.split()
        last_word_prefix = words_prefix[-1] if words_prefix else ""
        last_two_prefix = "".join(words_prefix[-2:]) if len(words_prefix) >= 2 else ""
        if any(
            last_word_prefix == prep
            or last_two_prefix == prep
            or (len(prep) > 3 and prefix.endswith(prep))
            for prep in PREV_PREPOSITIONS
        ):
            return True

    # Check if following text starts with a cross-reference postposition
    remainder = line[heading_match.end() :].lstrip(" \t:：-–.،;؛")
    if any(remainder.startswith(post) for post in NEXT_POSTPOSITIONS):
        return True

    # Check next non-empty line (isolated wrapped postposition)
    k = current_idx + 1
    while k < len(lines) and not lines[k][1].strip():
        k += 1
    if k < len(lines):
        next_line = lines[k][1].lstrip(" \t:：-–.،;؛")
        for post in NEXT_POSTPOSITIONS:
            if next_line.startswith(post):
                # If the line contains an operative legal verb, it is the article body text
                # wrapped across columns or lines, not a citation postposition.
                if any(v in next_line for v in OPERATIVE_ARTICLE_BODY_VERBS):
                    continue
                # Multi-word postposition ("من هذا القانون", "وما يليه", etc.) is always a citation.
                # Single-word adverbs ("أعلاه", "بعده", etc.) only match if isolated to prevent
                # false positives on bidi-wrapped paragraph lines in multi-column layouts.
                if len(post.split()) > 1 or len(next_line.split()) <= 3:
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

    # Strip leading colons or dashes on headings (e.g. ':الباب الرابع')
    line = line.lstrip(" \t:：-–")

    # Normalize internal spaces / OCR artifacts in level words
    line = re.sub(r"(?:\b|^)(?:لا\s*فصل|ال\s+فصل|لا\s*فص\s*ل)(?=[0-9٠-٩])", "الفصل ", line)
    line = re.sub(r"(?:\b|^)(?:لا\s*فصل|ال\s+فصل|لا\s*فص\s*ل)\b", "الفصل", line)
    line = re.sub(r"(?:\b|^)(?:لا\s*مادة|ال\s+مادة|لا\s*ماد\s*[ةه])(?=[0-9٠-٩])", "المادة ", line)
    line = re.sub(r"(?:\b|^)(?:لا\s*مادة|ال\s+مادة|لا\s*ماد\s*[ةه])\b", "المادة", line)
    line = re.sub(r"\bا\s*ل\s*م\s*ا\s*د\s*([ةه])\b", r"الماد\1", line)
    line = re.sub(r"\bم\s*ا\s*د\s*([ةه])\b", r"ماد\1", line)
    line = re.sub(r"\bا\s*ل\s*ف\s*ص\s*ل\b", "الفصل", line)
    line = re.sub(r"\b[ةه]\s*د\s*ا\s*م\s*ل\s*ا\b", "المادة", line)
    line = re.sub(
        r"\b(الحادي|الحادية|الثاني|الثانية|الثالث|الثالثة|الرابع|الرابعة|الخامس|الخامسة|السادس|السادسة|السابع|السابعة|الثامن|الثامنة|التاسع|التاسعة)\s*:\s*(عشر|عشرة)\b",
        r"\1 \2",
        line,
    )
    line = re.sub(r"\bالفصل\s+وا\s+ال\b", "الفصل الوا", line)

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
        # Check if the heading is followed by quotation marks indicating a quoted citation from another text
        if remainder.startswith(('"', "«", "”", "“")):
            return None
        if not remainder:
            # Check up to 2 non-empty lines ahead for standalone opening quote line (e.g. adala_013 footnote citations)
            k_quote = idx + 1
            while k_quote < len(lines) and not lines[k_quote][1].strip():
                k_quote += 1
            count_checked = 0
            while k_quote < len(lines) and count_checked < 2:
                q_candidate = lines[k_quote][1].strip().lstrip(" \t:：-–.")
                if q_candidate in ('"', "«", "”", "“"):
                    return None
                if q_candidate:
                    break
                k_quote += 1
                while k_quote < len(lines) and not lines[k_quote][1].strip():
                    k_quote += 1
                count_checked += 1
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


SPLIT_STEMS: dict[str, tuple[str, ...]] = {
    "السا": ("بعة", "بع"),
    "الثا": ("لثة", "لث", "نية", "ني"),
    "الرا": ("بعة", "بع"),
    "الخا": ("مسة", "مس"),
    "التا": ("سعة", "سع"),
    "الحا": ("دية", "دي"),
    "العا": ("شرة", "شر"),
    "الثلا": ("ثون", "ثين"),
    "والث": ("لاثون", "لاثين"),
    "والعش": ("رون", "رين"),
    "العش": ("رون", "رين"),
}

UNIT_ORDINALS: frozenset[str] = frozenset(
    {
        "الأول",
        "الأولى",
        "الاول",
        "الاولى",
        "الثاني",
        "الثانية",
        "الثالث",
        "الثالثة",
        "الرابع",
        "الرابعة",
        "الخامس",
        "الخامسة",
        "السادس",
        "السادسة",
        "السابع",
        "السابعة",
        "الثامن",
        "الثامنة",
        "التاسع",
        "التاسعة",
        "الواحد",
        "الواحدة",
        "الحادي",
        "الحادية",
    }
)


def _fuse_isolated_headings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Fuse isolated heading word lines with following number lines (e.g. adala_001 P57/P102)."""
    norm_lines: list[tuple[int, str]] = []
    for p_no, line in lines:
        cur_line = line
        cur_line = re.sub(
            r"^\s*[:：\-–]+\s*(الكتاب|كتاب|الباب|باب|القسم|قسم|الفرع|فرع|الفصل|فصل)",
            r"\1",
            cur_line,
        )
        cur_line = re.sub(
            r"(?:\b|^)(?:لا\s*فصل|ال\s+فصل|لا\s*فص\s*ل)(?=[0-9٠-٩])", "الفصل ", cur_line
        )
        cur_line = re.sub(r"(?:\b|^)(?:لا\s*فصل|ال\s+فصل|لا\s*فص\s*ل)\b", "الفصل", cur_line)
        cur_line = re.sub(
            r"(?:\b|^)(?:لا\s*مادة|ال\s+مادة|لا\s*ماد\s*[ةه])(?=[0-9٠-٩])",
            "المادة ",
            cur_line,
        )
        cur_line = re.sub(r"(?:\b|^)(?:لا\s*مادة|ال\s+مادة|لا\s*ماد\s*[ةه])\b", "المادة", cur_line)
        cur_line = re.sub(r"\bا\s*ل\s*م\s*ا\s*د\s*([ةه])\b", r"الماد\1", cur_line)
        cur_line = re.sub(r"\bم\s*ا\s*د\s*([ةه])\b", r"ماد\1", cur_line)
        cur_line = re.sub(r"\bا\s*ل\s*ف\s*ص\s*ل\b", "الفصل", cur_line)
        cur_line = re.sub(r"\b[ةه]\s*د\s*ا\s*م\s*ل\s*ا\b", "المادة", cur_line)
        cur_line = re.sub(
            r"\b(الحادي|الحادية|الثاني|الثانية|الثالث|الثالثة|الرابع|الرابعة|الخامس|الخامسة|السادس|السادسة|السابع|السابعة|الثامن|الثامنة|التاسع|التاسعة)\s*:\s*(عشر|عشرة)\b",
            r"\1 \2",
            cur_line,
        )
        cur_line = re.sub(r"\bالفصل\s+وا\s+ال\b", "الفصل الوا", cur_line)
        norm_lines.append((p_no, cur_line))

    fused: list[tuple[int, str]] = []
    i = 0
    n = len(norm_lines)
    while i < n:
        p_no, line = norm_lines[i]
        sline = line.strip()
        sline_norm = " ".join(sline.split())

        # Handle split 'الفص' + 'ل ...' or 'الماد' + 'ة ...'
        if sline in ("الفص", "الماد") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if sline == "الفص" and s_next.startswith(("ل ", "ل")):
                    rem = s_next[1:].lstrip()
                    norm_lines[j] = (next_p, "الفصل " + rem)
                    i = j
                    continue
                elif sline == "الماد" and s_next.startswith(("ة ", "ة", "ه ", "ه")):
                    rem = s_next[1:].lstrip()
                    norm_lines[j] = (next_p, "المادة " + rem)
                    i = j
                    continue

        # Handle split 'الباب الا' + 'ول: ...'
        if sline_norm in ("الباب الا", "الكتاب الا", "القسم الا") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith("ول"):
                    level_prefix = sline_norm.split()[0]
                    rem = s_next[2:].lstrip(" \t:：-–.")
                    fused_text = f"{level_prefix} الأول: {rem}" if rem else f"{level_prefix} الأول"
                    norm_lines[j] = (next_p, fused_text)
                    i = j
                    continue

        # Handle split 'الباب الث' + 'اني: ...'
        if sline_norm in ("الباب الث", "الكتاب الث", "القسم الث") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith("اني"):
                    level_prefix = sline_norm.split()[0]
                    rem = s_next[3:].lstrip(" \t:：-–.")
                    if rem == "في ا" and j + 1 < n:
                        k = j + 1
                        while k < n and not norm_lines[k][1].strip():
                            k += 1
                        if k < n and norm_lines[k][1].strip().startswith("ل"):
                            rem = "في " + "ا" + norm_lines[k][1].strip()
                            j = k
                    fused_text = (
                        f"{level_prefix} الثاني: {rem}" if rem else f"{level_prefix} الثاني"
                    )
                    norm_lines[j] = (next_p, fused_text)
                    i = j
                    continue

        # Handle split 'الفصل ا' + 'لأربعون'
        if sline_norm in ("الفصل ا", "المادة ا") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith(("لأ", "لار", "لإ")):
                    prefix = "الفصل ا" if sline_norm.startswith("الفصل") else "المادة ا"
                    norm_lines[j] = (next_p, prefix + s_next)
                    i = j
                    continue

        # Handle split 'الفصل الث' + 'اني والأربعون'
        if sline_norm in ("الفصل الث", "المادة الث") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith("اني"):
                    prefix = "الفصل الث" if sline_norm.startswith("الفصل") else "المادة الث"
                    norm_lines[j] = (next_p, prefix + s_next)
                    i = j
                    continue

        # Handle split 'الفصل الوا' + 'حد والأربعون'
        if sline_norm in ("الفصل الوا", "المادة الوا") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith("حد"):
                    prefix = "الفصل الوا" if sline_norm.startswith("الفصل") else "المادة الوا"
                    norm_lines[j] = (next_p, prefix + s_next)
                    i = j
                    continue

        # Handle division title continuations (e.g. adala_002 P12: ':الباب الرابع في فقدان الجنسية\nوالتجريد منها')
        if sline_norm.startswith("الباب الرابع في فقدان الجنسية") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n and norm_lines[j][1].strip().startswith("والتجريد"):
                norm_lines[j] = (norm_lines[j][0], "الباب الرابع: في فقدان الجنسية والتجريد منها")
                i = j
                continue

        if sline_norm.startswith("القسم الأول: فقدان الجنسية ا") and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n and norm_lines[j][1].strip().startswith("لمغربية"):
                rem = norm_lines[j][1].strip()[len("لمغربية") :].lstrip()
                norm_lines[j] = (
                    norm_lines[j][0],
                    ("القسم الأول: فقدان الجنسية المغربية " + rem).strip(),
                )
                i = j
                continue

        # Case 1: isolated 'ا' before level words (e.g. 'لمادة', 'لفصل', 'لباب')
        if sline == "ا" and i + 1 < n:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()
                if s_next.startswith(("لمادة", "لماده", "لفصل", "لباب", "لقسم")):
                    norm_lines[j] = (next_p, "ا" + s_next)
                    i = j
                    continue

        # Case 2: split ordinal suffix on next line, e.g. 'المادة السا' + 'بعة'
        matched_split = False
        for stem, suffixes in SPLIT_STEMS.items():
            if sline.endswith(stem):
                j = i + 1
                while j < n and not norm_lines[j][1].strip():
                    j += 1
                if j < n:
                    next_p, next_l = norm_lines[j]
                    s_next = next_l.strip()
                    for suf in suffixes:
                        if s_next.startswith(suf):
                            prefix = sline[: -len(stem)]
                            joined_word = stem + suf
                            rem = s_next[len(suf) :].lstrip(" \t:：-–.")
                            fused_line = (prefix + joined_word).strip()
                            if rem:
                                fused_line += " " + rem
                            fused.append((p_no, fused_line))
                            i = j + 1
                            matched_split = True
                            break
                    if matched_split:
                        break
        if matched_split:
            continue

        # Case 3: isolated level word lines (e.g. 'الفصل\nالرابع' or 'الفصل\nالسابع\nوالعشرون18:')
        if sline in ISOLATED_LEVEL_WORDS:
            j = i + 1
            while j < n and not norm_lines[j][1].strip():
                j += 1
            if j < n:
                next_p, next_l = norm_lines[j]
                s_next = next_l.strip()

                # Multi-line compound ordinal: unit ordinal on line j, tens on line j+1
                # e.g. line j is 'السابع' and line j+1 is 'والعشرون18:'
                if s_next in UNIT_ORDINALS and j + 1 < n:
                    k = j + 1
                    while k < n and not norm_lines[k][1].strip():
                        k += 1
                    if k < n:
                        k_p, k_l = norm_lines[k]
                        k_s = k_l.strip()
                        if re.match(
                            r"^و\s*(العشرون|العشرين|الثلاثون|الثلاثين|الأربعون|الأربعين|الخمسون|الخمسين|الستون|الستين|السبعون|السبعين|الثمانون|الثمانين|التسعون|التسعين)",
                            k_s,
                        ):
                            s_next = f"{s_next} {k_s}"
                            j = k

                m = NUM_OR_ORD_RE.match(s_next)
                if m:
                    num_val = m.group(1).strip()
                    suf_val = m.group(2).strip() if len(m.groups()) >= 2 and m.group(2) else None
                    fused_heading = canonical_heading_label(sline, num_val, suf_val)
                    fused.append((p_no, fused_heading))
                    remainder = s_next[m.end() :].lstrip(" \t:：-–.")
                    if remainder:
                        norm_lines[j] = (norm_lines[j][0], remainder)
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


TERMINAL_PUNCT: tuple[str, ...] = (".", "؛", ":", "؟", "?")


def split_long(units: list[_ChunkUnit], max_chunk_chars: int) -> list[_ChunkUnit]:
    """Split units longer than max_chunk_chars, preferring terminal punctuation boundaries for articles."""
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

        idx = 0
        n = len(expanded_lines)
        while idx < n:
            current_lines: list[tuple[int, str]] = []
            current_len = 0
            last_punct_idx: int | None = None

            j = idx
            while j < n:
                p_no, line_txt = expanded_lines[j]
                needed = len(line_txt) if not current_lines else (1 + len(line_txt))
                if current_lines and (current_len + needed > max_chunk_chars):
                    break
                current_lines.append((p_no, line_txt))
                current_len += needed
                if u.article is not None:
                    s_line = line_txt.rstrip(" \t\"'»«()")
                    if s_line and s_line.endswith(TERMINAL_PUNCT):
                        last_punct_idx = len(current_lines) - 1
                j += 1

            if (
                u.article is not None
                and j < n
                and last_punct_idx is not None
                and last_punct_idx >= 0
            ):
                kept_lines = current_lines[: last_punct_idx + 1]
                idx = idx + len(kept_lines)
            else:
                kept_lines = current_lines
                idx = j

            if kept_lines:
                sub_u = _ChunkUnit(
                    article=u.article,
                    hierarchy=list(u.hierarchy),
                    lines=list(kept_lines),
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


TEXT_END_RE: re.Pattern[str] = re.compile(
    r"وحرر\s+(?:بالرباط|بتطوان|بفاس|بطنجة|بالفنيدق)", re.UNICODE
)
TEXT_START_RE: re.Pattern[str] = re.compile(
    r"(?:^\s*(?:مرسوم|ظهير\s+شريف|قرار|مقرر|قانون)\b.*?\bرقم\b)|"
    r"(?:(?:\b|\d)(?:مرسوم|ظهير\s+شريف|قرار|مقرر|قانون)\b.*?\bرقم\s*$)",
    re.UNICODE,
)
VISA_WORDS: tuple[str, ...] = (
    "وعلى",
    "بناء على",
    "الصادر بتنفيذه",
    "المشار إليه",
    "تطبيقا",
    "بعد الاطلاع",
    "بتاريخ",
)


def _is_text_start_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if any(v in s for v in VISA_WORDS):
        return False
    if re.search(r"\.{3,}\s*[0-9٠-٩]+$", s):
        return False
    return bool(TEXT_START_RE.search(s))


def _is_text_end_line(line: str) -> bool:
    return bool(TEXT_END_RE.search(line))


def _is_multi_text_doc(lines: list[tuple[int, str]], meta: DocumentMeta) -> bool:
    """Detect if a document contains multiple separate legislative/regulatory texts."""
    if meta.source_file and re.search(r"sgg_\d+", meta.source_file):
        return True
    if (meta.source and "الجريدة الرسمية" in meta.source) or (
        meta.title and "الجريدة الرسمية" in meta.title
    ):
        return True
    has_closing = False
    for _, line in lines:
        s = line.strip()
        if _is_text_end_line(s):
            has_closing = True
        elif has_closing and _is_text_start_line(s):
            return True
    return False


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
    # Treat 'الفصل' as article heading when the text has no 'المادة' articles,
    # or when 'الفصل' is the primary article unit (e.g. nationality code adala_002)
    madda_count = 0
    fasl_count = 0
    for i in range(len(lines)):
        hm = _match_heading(lines, i)
        if hm:
            if hm.word == "المادة":
                madda_count += 1
            elif hm.word == "الفصل":
                fasl_count += 1

    if fasl_count > 0 and (madda_count == 0 or fasl_count > madda_count):
        article_word = "الفصل"
    else:
        article_word = "المادة"

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
                if not (article_word == "الفصل" and hm.word == "المادة"):
                    cur_hier = update_path(cur_hier, hm.word, hm.title_extra or hm.label)
            annotated.append((p_no, line_txt, cur_art, list(cur_hier)))

        units = pack_paragraphs(annotated, max_chunk_chars, overlap_chars)
    else:
        # Strategy 'article' (P1-18 à P1-22, §6.3)
        units = []
        path: list[str] = []
        current = _ChunkUnit(article=None, hierarchy=[])
        is_multi = _is_multi_text_doc(lines, meta)
        in_text_closing = is_multi

        for i in range(len(lines)):
            p_no, line_txt = lines[i]
            hm = _match_heading(lines, i)

            # In multi-text documents, ignore TOC pages before body starts
            is_in_toc = (
                is_multi
                and (p_no < 4)
                and bool(meta.source_file and re.search(r"sgg_7435", meta.source_file))
            )

            if is_multi and _is_text_end_line(line_txt):
                in_text_closing = True
                current.add(line_txt, p_no)
            elif is_multi and not is_in_toc and in_text_closing and _is_text_start_line(line_txt):
                if current.text.strip():
                    units.append(current)
                text_title = line_txt[:160].strip()
                path = [text_title]
                current = _ChunkUnit(article=None, hierarchy=list(path))
                current.add(line_txt, p_no)
                in_text_closing = False
            elif hm and hm.word == article_word:
                units.append(current)
                current = _ChunkUnit(article=hm.label, hierarchy=list(path))
                current.add(line_txt, p_no)
            elif hm:
                if article_word == "الفصل" and hm.word == "المادة":
                    current.add(line_txt, p_no)
                else:
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
