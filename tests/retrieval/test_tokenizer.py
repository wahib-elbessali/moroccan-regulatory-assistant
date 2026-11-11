"""Tests of the BM25 tokenizer (P2 spec P2-20, P2-22, §6.6)."""

import pytest

from src.ingestion import normalize_ar
from src.retrieval.tokenizer import STOPWORDS, STOPWORDS_PATH, light_stem, load_stopwords, tokenize

# Words the spec lists as stopwords (P2-20), in normalized form.
SPEC_STOPWORDS = [
    "في",
    "من",
    "علي",
    "الي",
    "عن",
    "ان",
    "او",
    "و",
    "التي",
    "الذي",
    "هذا",
    "هذه",
    "ذلك",
    "كل",
    "لا",
    "ما",
]


def test_single_letters_dropped_digits_kept() -> None:
    assert tokenize(normalize_ar("ب المادة 5")) == ["الماده", "5"]


def test_single_digit_kept() -> None:
    assert tokenize("الماده 5") == ["الماده", "5"]


def test_single_latin_letter_dropped() -> None:
    assert tokenize("a loi") == ["loi"]


def test_only_stopwords_gives_no_token() -> None:  # T19, tokenizer side
    assert tokenize(normalize_ar("في من على")) == []


def test_stopwords_removed_inside_text() -> None:
    text = normalize_ar("يتعين على المصالح معالجة الطلبات في أجل ثلاثين يوما")
    assert tokenize(text) == ["يتعين", "المصالح", "معالجه", "الطلبات", "اجل", "ثلاثين", "يوما"]


def test_law_number_is_split_into_digits() -> None:
    assert tokenize(normalize_ar("القانون رقم 31.08")) == ["القانون", "رقم", "31", "08"]


def test_article_reference_keeps_number() -> None:
    assert tokenize(normalize_ar("المادة 12")) == ["الماده", "12"]


@pytest.mark.parametrize("text", ["", "   ", "و ب ك"])
def test_nothing_left_gives_empty_list(text: str) -> None:
    assert tokenize(text) == []


def test_order_is_kept() -> None:
    assert tokenize("رقم القانون") == ["رقم", "القانون"]


def test_same_function_for_chunk_and_query() -> None:
    chunk = normalize_ar("المادة 2: يتعين على المصالح المختصة معالجة الطلبات.")
    query = normalize_ar("معالجة الطلبات")
    assert set(tokenize(query)) <= set(tokenize(chunk))


def test_stopword_file_is_not_empty() -> None:
    assert STOPWORDS


def test_every_stopword_is_normalized() -> None:
    assert all(normalize_ar(w) == w for w in STOPWORDS)


@pytest.mark.parametrize("word", SPEC_STOPWORDS)
def test_spec_stopwords_are_present(word: str) -> None:
    assert word in STOPWORDS


def test_stopword_file_has_one_word_per_line() -> None:
    lines = STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
    assert all(line == line.strip() and line and " " not in line for line in lines)
    assert len(lines) == len(set(lines))


def test_load_stopwords_ignores_blank_lines_and_bom(tmp_path) -> None:
    path = tmp_path / "stopwords.txt"
    path.write_text("\ufeff\u0641\u064a\n\n\u0645\u0646\n", encoding="utf-8")
    assert load_stopwords(path) == frozenset({"في", "من"})


def test_light_stem_is_identity_in_minimum_version() -> None:
    assert light_stem("والقانون") == "والقانون"
