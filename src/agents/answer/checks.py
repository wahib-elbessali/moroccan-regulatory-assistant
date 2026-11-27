"""Checks in code on each claim the Juge accepted (P4-13, P4-14).

The small model (qwen2.5:3b, light mode) accepts almost every claim it is asked about, so a claim
the Juge accepted is checked again here, without a model, against the question and the text of
the source it cites. A claim that fails one check is dropped like an unsupported claim.
"""

from __future__ import annotations

import re

from src.core.contracts import detect_language
from src.ingestion.normalize import normalize_ar
from src.retrieval.tokenizer import tokenize

_MARKER_RE = re.compile(r"\[\d+\]")
_NUMBER_RE = re.compile(r"\d+")
# PDF text often glues a number to the word before it ("بتاريخ23", "المادة23").
_LETTER_DIGIT_RE = re.compile(r"(?<=[^\d\s])(?=\d)|(?<=\d)(?=[^\d\s])")
# A claim that ends on "هي" / "هو" before its marker announces an answer it does not give.
_EMPTY_ENDINGS = frozenset(normalize_ar(word) for word in ("هي", "هو", "هم", "يلي", "كالتالي"))
# Chinese, Japanese and Korean characters: the small model sometimes mixes them into Arabic.
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# Darija verbs written with the prefix كي (كيعطي, كيقرر, كيتعتبر). "كيف", "كيفية", "كيان" and
# "كيلومتر" do not match.
_DARIJA_VERB_RE = re.compile(r"(?<!\S)كي(?!ف|ان|ل)\S{3,}")
_DARIJA_WORDS = frozenset(
    normalize_ar(word)
    for word in ("واش", "ديال", "شنو", "فاش", "باش", "شحال", "علاش", "كاين", "ماشي", "دابا")
)

# A claim that says the sources do not contain the answer is not an answer.
_MISSING_PHRASES = tuple(
    normalize_ar(phrase)
    for phrase in (
        "لا يذكر",
        "لا تذكر",
        "لم يذكر",
        "لم تذكر",
        "لم يرد",
        "لا يتضمن",
        "لا تتضمن",
        "غير مذكور",
        "لا توجد معلومات",
        "لا توجد معلومة",
        "pas explicitement",
        "ne sont pas couvert",
        "n'est pas couvert",
        "ne mentionne pas",
        "ne précise pas",
        "aucune information",
        "pas d'information",
    )
)
_AT_LEAST = tuple(
    normalize_ar(phrase) for phrase in ("على الأقل", "لا يقل", "لا تقل", "au moins", "au minimum")
)
_AT_MOST = tuple(
    normalize_ar(phrase)
    for phrase in (
        "على الأكثر",
        "لا يتجاوز",
        "لا تتجاوز",
        "لا يتعدى",
        "لا تتعدى",
        "أقصاه",
        "au plus",
        "au maximum",
    )
)

NEW_WORDS_IN_SOURCE = 0.7
TOPIC_WORDS_IN_SOURCE = 0.5
MIN_TOPIC_WORDS = 3


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    """A phrase starts at a word boundary of the normalized text ("couvert" matches "couvertes")."""
    padded = f" {text}"
    return any(f" {phrase}" in padded for phrase in phrases)


def _prepare(text: str) -> str:
    return normalize_ar(_LETTER_DIGIT_RE.sub(" ", text))


def _in_source(word: str, source_words: set[str], source_joined: str) -> bool:
    """The word is in the source, allowing for PDF words split by a space ("سن وات") and for
    prefixes and endings the stemmer leaves ("بشؤون" for "شؤون", "رايه" for "راي")."""
    if word in source_words:
        return True
    if len(word) < 4:
        return False
    return word in source_joined or word[1:] in source_joined


def _share(words: set[str], source_words: set[str], source_joined: str) -> float:
    return sum(_in_source(word, source_words, source_joined) for word in words) / len(words)


def claim_problem(claim: str, question: str, source_text: str, excerpt: str) -> str | None:
    """Why a claim the Juge accepted must still be dropped, or ``None`` if it passes.

    Args:
        claim: The claim as the writer wrote it, with its markers.
        question: The user's question.
        source_text: Title, article label and text of the source the claim cites.
        excerpt: The excerpt checked in that source.

    Returns:
        ``foreign_script``, ``darija``, ``no_information``, ``number_mismatch``,
        ``limit_mismatch``, ``no_new_information``, ``not_in_source``, ``off_topic`` or ``None``.
    """
    text = _MARKER_RE.sub(" ", claim)
    if _CJK_RE.search(text):
        return "foreign_script"
    normalized = _prepare(text)
    arabic = detect_language(text) == "ar"
    if arabic and (_DARIJA_VERB_RE.search(normalized) or _DARIJA_WORDS & set(normalized.split())):
        return "darija"
    if _has(normalized, _MISSING_PHRASES):
        return "no_information"

    if normalized.split() and normalized.split()[-1] in _EMPTY_ENDINGS:
        return "no_new_information"

    source = _prepare(source_text)
    source_numbers = set(_NUMBER_RE.findall(source))
    if any(number not in source_numbers for number in _NUMBER_RE.findall(normalized)):
        return "number_mismatch"

    near = _prepare(excerpt) or source
    if _has(normalized, _AT_LEAST) and _has(near, _AT_MOST) and not _has(near, _AT_LEAST):
        return "limit_mismatch"
    if _has(normalized, _AT_MOST) and _has(near, _AT_LEAST) and not _has(near, _AT_MOST):
        return "limit_mismatch"

    if not arabic:
        # A French claim shares no words with an Arabic source; only the checks above apply.
        return None
    words = {word for word in tokenize(normalized) if not word.isdigit()}
    if not words:
        return "no_new_information"
    question_words = set(tokenize(_prepare(question)))
    source_words = set(tokenize(source))
    source_joined = source.replace(" ", "")
    new_words = words - question_words
    if not new_words:
        return "no_new_information"
    if _share(new_words, source_words, source_joined) < NEW_WORDS_IN_SOURCE:
        return "not_in_source"
    topic_words = words & question_words
    if len(topic_words) >= MIN_TOPIC_WORDS and (
        _share(topic_words, source_words, source_joined) < TOPIC_WORDS_IN_SOURCE
    ):
        return "off_topic"
    return None
