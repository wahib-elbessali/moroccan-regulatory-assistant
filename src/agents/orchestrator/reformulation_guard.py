"""Guards for planned and reformulated queries (P3). Pure functions, no dependency on the repo.

A reformulation is accepted only if it keeps the content words of the question
(legal terms) and every part of a multi-part question. Otherwise the caller
should fall back to the original query.

The same part check is applied to the plan: if the planner drops a part of an Arabic
question, that part is added back as its own sub-question.
"""

import re

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_WORD = re.compile(r"\w+", re.UNICODE)
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_SPLIT = re.compile(r"[؟?]|،\s*(?=و)|\s(?=و(?:لمن|ما|ماذا|كيف|متى|أين|هل|من)\s)")

STOP = {
    "ما",
    "ماذا",
    "هي",
    "هو",
    "من",
    "في",
    "على",
    "عن",
    "كل",
    "التي",
    "الذي",
    "يجب",
    "هل",
    "كيف",
    "متى",
    "أين",
    "إلى",
    "الى",
    "مع",
    "أو",
    "او",
    "ذلك",
    "هذا",
    "هذه",
}


def _norm(word: str) -> str:
    w = _DIACRITICS.sub("", word.lower())
    w = w.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    if w.startswith("و") and len(w) > 3:
        w = w[1:]
    for prefix in ("لل", "ال", "بال", "كال", "فال"):
        if w.startswith(prefix) and len(w) > len(prefix) + 1:
            return w[len(prefix) :]
    return w


def content_words(text: str) -> set[str]:
    return {n for w in _WORD.findall(text) if len(n := _norm(w)) > 2 and n not in STOP}


def question_parts(question: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT.split(question) if p and len(content_words(p)) >= 1]
    return parts or [question]


def keeps_meaning(question: str, new_query: str, min_ratio: float = 0.5) -> bool:
    """True if new_query keeps >= min_ratio of the question's content words
    and touches every part of the question."""
    q_words, n_words = content_words(question), content_words(new_query)
    if not q_words:
        return True
    if len(q_words & n_words) / len(q_words) < min_ratio:
        return False
    return all(content_words(p) & n_words for p in question_parts(question))


def is_arabic(text: str) -> bool:
    """True if most letters of the text are Arabic (the part check only works on Arabic)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if _ARABIC.match(c)) / len(letters) > 0.5


def missing_parts(question: str, sub_questions: list[str]) -> list[str]:
    """Parts of an Arabic question that no sub-question touches. Empty for other languages."""
    if not is_arabic(question):
        return []
    parts = question_parts(question)
    if len(parts) < 2:  # a single-part question has nothing to drop
        return []
    covered: set[str] = set()
    for sub in sub_questions:
        covered |= content_words(sub)
    return [p for p in parts if not content_words(p) & covered]


# --- French questions -------------------------------------------------------------------------
# The planner writes Arabic sub-questions for a French question, so French and Arabic share no
# word. A small lexicon maps the key French terms to Arabic stems: a part of the question is
# covered when one of its terms appears in the plan. It only knows the terms listed here.

_FR_SPLIT = re.compile(
    r"\?|,\s*(?:et|puis)\s+|\s+et\s+(?=(?:à qui|à quoi|quels?|quelles?|quand|où|comment|combien)\b)",
    re.IGNORECASE,
)


def _flat(text: str) -> str:
    """Arabic text without diacritics, with the letter variants merged (for stem matching)."""
    t = _DIACRITICS.sub("", text.lower())
    return (
        t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    )


# (French pattern, Arabic stems that cover it, Arabic words to rebuild a query, is a question word)
_FR_TERMS: list[tuple[re.Pattern[str], tuple[str, ...], str, bool]] = [
    (re.compile(r"\bà qui\b", re.I), ("لمن", "الى من", "جهة", "من يقدم"), "لمن يقدم", True),
    (re.compile(r"\bcombien\b", re.I), ("مبلغ", "كم", "عدد", "مدة"), "كم", True),
    (re.compile(r"\bquand\b", re.I), ("متى", "تاريخ", "اجل", "مدة", "مهلة"), "متى", True),
    (re.compile(r"\boù\b", re.I), ("اين", "مكان", "جهة", "لدى"), "اين", True),
    (
        re.compile(r"\bdocuments?\b|\bpièces?\b", re.I),
        ("وثائق", "وثيقه", "مستند"),
        "الوثائق",
        False,
    ),
    (re.compile(r"\bveuves?\b", re.I), ("ارمل", "ارامل"), "الأرملة", False),
    (re.compile(r"\bvulnérabilité\b", re.I), ("هش",), "وضعية هشة", False),
    (re.compile(r"\bconditions?\b", re.I), ("شروط", "شرط"), "الشروط", False),
    (re.compile(r"\bdurée\b|\bdélai\b", re.I), ("مدة", "اجل", "مهلة"), "المدة", False),
    (re.compile(r"\bmontant\b", re.I), ("مبلغ",), "المبلغ", False),
    (re.compile(r"\bdemande\b|\bdossier\b", re.I), ("طلب", "ملف"), "طلب", False),
    (re.compile(r"\bsoutien\b|\baide\b", re.I), ("دعم", "مساعد"), "الدعم", False),
]


_FR_WORDS = {
    "le", "la", "les", "des", "du", "un", "une", "est", "sont", "quel", "quels", "quelle",
    "quelles", "pour", "dans", "sur", "qui", "que", "quoi", "doit", "doivent", "peut", "et",
    "à", "où", "comment", "combien", "quand", "par", "en", "au", "aux",
}  # fmt: skip


def is_french(text: str) -> bool:
    """Latin-script text with at least two French function words (English and Latin-script
    Darija must not be taken for French)."""
    letters = [c for c in text if c.isalpha()]
    if (
        not letters
        or sum(1 for c in letters if c.isascii() or c in "àâçéèêëîïôùûüœ") / len(letters) <= 0.8
    ):
        return False
    words = re.findall(r"[\wàâçéèêëîïôùûüœ]+", text.lower())
    return sum(1 for w in words if w in _FR_WORDS) >= 2


def french_parts(question: str) -> list[str]:
    return [p.strip() for p in _FR_SPLIT.split(question) if p and len(p.split()) >= 2]


def _fr_terms(part: str) -> list[tuple[tuple[str, ...], str, bool]]:
    found = [
        (m.start(), stems, words, ask)
        for rx, stems, words, ask in _FR_TERMS
        if (m := rx.search(part))
    ]
    return [(stems, words, ask) for _, stems, words, ask in sorted(found)]


def missing_french_parts(question: str, sub_questions: list[str]) -> list[str]:
    """An Arabic query for each part of a French question that the plan does not cover.

    A part is covered when the plan holds an Arabic stem of its question word ("à qui" -> لمن),
    or, without a question word, of any of its known terms. A part with no known term is not
    checked.
    """
    parts = french_parts(question)
    if len(parts) < 2:
        return []
    flat = _flat(" ".join(sub_questions))
    missing: list[str] = []
    for part in parts:
        terms = _fr_terms(part)
        check = [t for t in terms if t[2]] or terms
        if not check:
            continue
        if any(_flat(stem) in flat for stems, _, _ in check for stem in stems):
            continue
        query = " ".join(words for _, words, _ in terms)
        if query:
            missing.append(query)
    return missing


def complete_sub_questions(question: str, sub_questions: list[str], max_n: int) -> list[str]:
    """The plan with every dropped part of the question added back as a sub-question.

    If there is no room for them (max_n), the original question is searched as one
    sub-question: that is the planner's own fallback, and it loses no part.
    """
    if is_arabic(question):
        missing = missing_parts(question, sub_questions)
    elif is_french(question):
        missing = missing_french_parts(question, sub_questions)
    else:
        missing = []
    if not missing:
        return sub_questions
    if len(sub_questions) + len(missing) > max_n:
        return [question]
    return sub_questions + missing
