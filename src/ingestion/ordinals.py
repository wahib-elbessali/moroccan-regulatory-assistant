"""Arabic legal ordinals and heading pattern definitions (P1-18, §6.3)."""

from __future__ import annotations

import re

# Base single-word ordinals and legal qualifiers
BASE_ORDINALS: dict[str, str] = {
    # 1
    "الأول": "1",
    "الأولى": "1",
    "الاول": "1",
    "الاولى": "1",
    "الفريد": "1",
    "الفريدة": "1",
    "فريد": "1",
    "فريدة": "1",
    # 2
    "الثاني": "2",
    "الثانية": "2",
    # 3
    "الثالث": "3",
    "الثالثة": "3",
    # 4
    "الرابع": "4",
    "الرابعة": "4",
    # 5
    "الخامس": "5",
    "الخامسة": "5",
    # 6
    "السادس": "6",
    "السادسة": "6",
    # 7
    "السابع": "7",
    "السابعة": "7",
    # 8
    "الثامن": "8",
    "الثامنة": "8",
    # 9
    "التاسع": "9",
    "التاسعة": "9",
    # 10
    "العاشر": "10",
    "العاشرة": "10",
    # Special chapter qualifiers
    "التمهيدي": "0",
    "تمهيدي": "0",
}

# Compound ordinals 11 to 19
COMPOUND_11_19: dict[str, str] = {
    "الحادي عشر": "11",
    "الحادية عشرة": "11",
    "الحادي عشرة": "11",
    "الحادية عشر": "11",
    "الثاني عشر": "12",
    "الثانية عشرة": "12",
    "الثاني عشرة": "12",
    "الثانية عشر": "12",
    "الثالث عشر": "13",
    "الثالثة عشرة": "13",
    "الثالث عشرة": "13",
    "الثالثة عشر": "13",
    "الرابع عشر": "14",
    "الرابعة عشرة": "14",
    "الرابع عشرة": "14",
    "الرابعة عشر": "14",
    "الخامس عشر": "15",
    "الخامسة عشرة": "15",
    "الخامس عشرة": "15",
    "الخامسة عشر": "15",
    "السادس عشر": "16",
    "السادسة عشرة": "16",
    "السادس عشرة": "16",
    "السادسة عشر": "16",
    "السابع عشر": "17",
    "السابعة عشرة": "17",
    "السابع عشرة": "17",
    "السابعة عشر": "17",
    "الثامن عشر": "18",
    "الثامنة عشرة": "18",
    "الثامن عشرة": "18",
    "الثامنة عشر": "18",
    "التاسع عشر": "19",
    "التاسعة عشرة": "19",
    "التاسع عشرة": "19",
    "التاسعة عشر": "19",
}

# Tens ordinals 20 to 100
TENS_ORDINALS: dict[str, str] = {
    "العشرون": "20",
    "العشرين": "20",
    "الثلاثون": "30",
    "الثلاثين": "30",
    "الأربعون": "40",
    "الأربعين": "40",
    "الاربعون": "40",
    "الاربعين": "40",
    "الخمسون": "50",
    "الخمسين": "50",
    "الستون": "60",
    "الستين": "60",
    "السبعون": "70",
    "السبعين": "70",
    "الثمانون": "80",
    "الثمانين": "80",
    "التسعون": "90",
    "التسعين": "90",
    "المائة": "100",
    "المئة": "100",
}


def _build_ordinals_map() -> dict[str, str]:
    """Build comprehensive mapping of Arabic ordinal forms to numeric strings."""
    mapping = dict(BASE_ORDINALS)
    mapping.update(COMPOUND_11_19)
    mapping.update(TENS_ORDINALS)

    units_for_compounds = [
        ("الحادي", "1"),
        ("الحادية", "1"),
        ("الثاني", "2"),
        ("الثانية", "2"),
        ("الثالث", "3"),
        ("الثالثة", "3"),
        ("الرابع", "4"),
        ("الرابعة", "4"),
        ("الخامس", "5"),
        ("الخامسة", "5"),
        ("السادس", "6"),
        ("السادسة", "6"),
        ("السابع", "7"),
        ("السابعة", "7"),
        ("الثامن", "8"),
        ("الثامنة", "8"),
        ("التاسع", "9"),
        ("التاسعة", "9"),
    ]
    tens_for_compounds = [
        ("العشرون", 20),
        ("العشرين", 20),
        ("الثلاثون", 30),
        ("الثلاثين", 30),
        ("الأربعون", 40),
        ("الأربعين", 40),
        ("الاربعون", 40),
        ("الاربعين", 40),
        ("الخمسون", 50),
        ("الخمسين", 50),
        ("الستون", 60),
        ("الستين", 60),
        ("السبعون", 70),
        ("السبعين", 70),
        ("الثمانون", 80),
        ("الثمانين", 80),
        ("التسعون", 90),
        ("التسعين", 90),
    ]

    for u_label, u_val in units_for_compounds:
        for t_label, t_val in tens_for_compounds:
            num = str(int(u_val) + t_val)
            mapping[f"{u_label} و{t_label}"] = num
            mapping[f"{u_label} و {t_label}"] = num

    return mapping


ORDINALS_MAP: dict[str, str] = _build_ordinals_map()

# Regex pattern matching any recognized ordinal word, sorted longest first
ORDINALS_PATTERN: str = "|".join(
    re.escape(k) for k in sorted(ORDINALS_MAP.keys(), key=len, reverse=True)
)

# Hierarchy levels ordered from outermost to innermost (§6.3)
LEVELS: list[str] = ["الجزء", "الكتاب", "الباب", "القسم", "الفرع", "الفصل"]

ISOLATED_LEVEL_WORDS: frozenset[str] = frozenset(
    {
        "الكتاب",
        "كتاب",
        "الباب",
        "باب",
        "القسم",
        "قسم",
        "الفرع",
        "فرع",
        "الفصل",
        "فصل",
        "المادة",
        "مادة",
        "الجزء",
        "جزء",
    }
)

HEADING_START_RE = re.compile(
    rf"^\s*(الكتاب|كتاب|الباب|باب|القسم|قسم|الفرع|فرع|الفصل|فصل|ا\s*ل\s*ف\s*ص\s*ل|المادة|مادة|ا\s*ل\s*م\s*ا\s*د\s*[ةه]|الجزء|جزء)"
    rf"\s*([0-9٠-٩]+(?:[-–][0-9٠-٩]+)?|{ORDINALS_PATTERN})"
    rf"(?:\s+(مكرر\s+مرتين|مكرر))?"
    rf"(?=\s*[:：\-–.]|\s*$|\s+(?!من\s+|أعلاه|بعده|أدناه))",
    re.UNICODE,
)

HEADING_EOL_RE = re.compile(
    rf"^(.*?)\s*[-–]\s*([0-9٠-٩]+|{ORDINALS_PATTERN})\s+(ا\s*ل\s*م\s*ا\s*د\s*[ةه]|المادة|مادة|ا\s*ل\s*ف\s*ص\s*ل|الفصل|فصل)\s*$",
    re.UNICODE,
)

NUM_OR_ORD_RE = re.compile(
    rf"^([0-9٠-٩]+(?:[-–][0-9٠-٩]+)?|{ORDINALS_PATTERN})"
    rf"(?:\s+(مكرر\s+مرتين|مكرر))?"
    rf"(?=\s*[:：\-–.]|\s*$|\s+(?!من\s+|أعلاه|بعده|أدناه))",
    re.UNICODE,
)

PREV_PREPOSITIONS: tuple[str, ...] = (
    "أحكام",
    "مقتضيات",
    "بمقتضى",
    "وفقا ل",
    "وفقا لـ",
    "طبقا ل",
    "طبقا لـ",
    "مع مراعاة",
    "مراعاة",
    "عليها في",
    "المنصوص عليها في",
    "المادتين",
    "المواد",
    "الفصلين",
    "الفصول",
)

NEXT_POSTPOSITIONS: tuple[str, ...] = (
    "أعلاه",
    "بعده",
    "أدناه",
    "من هذا القانون",
    "من القانون",
    "من هذا",
    "من قانون",
    "السالف الذكر",
    "المشار إليه",
)


def normalize_level_word(word: str) -> str:
    """Normalize level word variants to standard canonical level representation."""
    clean = re.sub(r"\s+", "", word.strip())
    if clean in ("المادة", "مادة"):
        return "المادة"
    if clean in ("الفصل", "فصل"):
        return "الفصل"
    if clean in ("الباب", "باب"):
        return "الباب"
    if clean in ("الكتاب", "كتاب"):
        return "الكتاب"
    if clean in ("القسم", "قسم"):
        return "القسم"
    if clean in ("الفرع", "فرع"):
        return "الفرع"
    if clean in ("الجزء", "جزء"):
        return "الجزء"
    return clean


def canonical_heading_label(
    word: str,
    number_or_ordinal: str,
    suffix: str | None = None,
) -> str:
    """Produce canonical label: normalized level word, single space, number/ordinal, optional ' مكرر'."""
    clean_word = re.sub(r"\s+", "", word.strip())
    if clean_word in ("الماده", "المادة"):
        clean_word = "المادة"
    elif clean_word in ("ماده", "مادة"):
        clean_word = "مادة"
    elif clean_word in ("الفصل", "فصل"):
        clean_word = clean_word
    elif clean_word in ("الباب", "باب"):
        clean_word = clean_word
    elif clean_word in ("الكتاب", "كتاب"):
        clean_word = clean_word
    elif clean_word in ("القسم", "قسم"):
        clean_word = clean_word
    elif clean_word in ("الفرع", "فرع"):
        clean_word = clean_word
    elif clean_word in ("الجزء", "جزء"):
        clean_word = clean_word

    num = " ".join(number_or_ordinal.strip().split())
    base = f"{clean_word} {num}"
    if suffix:
        suf = " ".join(suffix.strip().split())
        return f"{base} {suf}"
    return base
