"""Tests of the BM25 tokenizer (P2 spec P2-20, P2-22, §6.6).

The words in the light_stem tests are real words of the corpus (data/raw).
"""

import pytest

from src.ingestion import normalize_ar
from src.retrieval.tokenizer import (
    PREFIXES,
    STOPWORDS,
    STOPWORDS_PATH,
    SUFFIXES,
    WAW_WORDS,
    light_stem,
    load_stopwords,
    tokenize,
)

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
    assert tokenize(normalize_ar("ب المادة 5")) == ["ماده", "5"]


def test_single_digit_kept() -> None:
    assert tokenize("الماده 5") == ["ماده", "5"]


def test_single_latin_letter_dropped() -> None:
    assert tokenize("a loi") == ["loi"]


def test_only_stopwords_gives_no_token() -> None:  # T19, tokenizer side
    assert tokenize(normalize_ar("في من على")) == []


def test_stopwords_removed_inside_text() -> None:
    text = normalize_ar("يتعين على المصالح معالجة الطلبات في أجل ثلاثين يوما")
    assert tokenize(text) == ["يتع", "مصالح", "معالجه", "طلب", "اجل", "ثلاث", "يوما"]


def test_law_number_is_split_into_digits() -> None:
    assert tokenize(normalize_ar("القانون رقم 31.08")) == ["قان", "رقم", "31", "08"]


def test_article_reference_keeps_number() -> None:
    assert tokenize(normalize_ar("المادة 12")) == ["ماده", "12"]


@pytest.mark.parametrize("text", ["", "   ", "و ب ك"])
def test_nothing_left_gives_empty_list(text: str) -> None:
    assert tokenize(text) == []


def test_order_is_kept() -> None:
    assert tokenize("رقم القانون") == ["رقم", "قان"]


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


# --- light_stem (P2-22): one test per rule, with a real word of the corpus ---------------------


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("والبيانات", "بيان"),  # prefix وال (then suffix ات)
        ("بالعدل", "عدل"),  # prefix بال
        ("كالوصيه", "وصيه"),  # prefix كال
        ("فالقول", "قول"),  # prefix فال
        ("للاختبار", "اختبار"),  # prefix لل
        ("الالتزام", "التزام"),  # prefix ال
    ],
)
def test_each_prefix_rule(word: str, stem: str) -> None:
    assert light_stem(word) == stem


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("الطلبات", "طلب"),  # suffix ات
        ("المفوضون", "مفوض"),  # suffix ون
        ("الزوجين", "زوج"),  # suffix ين
        ("حدودها", "حدود"),  # suffix ها
        ("مهامهم", "مهام"),  # suffix هم
    ],
)
def test_each_suffix_rule(word: str, stem: str) -> None:
    assert light_stem(word) == stem


def test_rule_lists_are_the_measured_ones() -> None:
    """ه is left out on purpose and lone و comes last, after WAW_WORDS (see the module
    docstring): a change here needs a new measurement and a new test per added rule."""
    assert PREFIXES == ("وال", "بال", "كال", "فال", "لل", "ال", "و")
    assert SUFFIXES == ("ات", "ون", "ين", "ها", "هم")


def test_longest_prefix_first() -> None:
    assert light_stem("والقانون") == "قان"  # وال, not just و or ال


def test_at_most_one_prefix_and_one_suffix() -> None:
    assert light_stem("للقانون") == "قان"  # لل removed, not لل then ال


def test_at_least_three_letters_are_kept() -> None:
    assert light_stem("الله") == "الله"  # removing ال would leave 2 letters
    assert light_stem("ذات") == "ذات"  # removing ات would leave 1 letter
    assert light_stem("سنوات") == "سنو"  # exactly 3 letters left: allowed


@pytest.mark.parametrize("word", ["وزير", "وثيقه", "وكيل", "وكاله"])
def test_lone_waw_is_not_a_prefix(word: str) -> None:
    """The و of these frequent nouns is part of the word: they are in WAW_WORDS."""
    assert word in WAW_WORDS
    assert light_stem(word) == word


def test_every_waw_word_keeps_its_waw() -> None:
    """A suffix may still go (وفاتهم → وفات), never the first و."""
    for word in WAW_WORDS:
        assert light_stem(word).startswith("و"), word


def test_waw_words_are_normalized_and_start_with_waw() -> None:
    """tokenize compares normalized tokens, so each entry must already be normalized."""
    for word in WAW_WORDS:
        assert word.startswith("و"), word
        assert normalize_ar(word) == word, word


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("وحمايه", "حمايه"),  # "and protection"
        ("وحدود", "حدود"),  # "and limits"
        ("ووزير", "وزير"),  # "and minister": one و removed, the word's own و kept
    ],
)
def test_conjunction_waw_is_removed(word: str, stem: str) -> None:
    assert light_stem(word) == stem


def test_waw_and_article_still_lose_wal() -> None:
    assert light_stem("والوزير") == "وزير"


def test_waw_and_stopword_is_dropped() -> None:
    assert tokenize("وذلك") == []  # و removed, then ذلك is a stopword


@pytest.mark.parametrize("word", ["معالجه", "الماده", "حمايه"])
def test_feminine_heh_is_not_a_suffix(word: str) -> None:
    """After normalize_ar, a final ه is mostly ة: معالجه must not become معالج ("processor")."""
    assert light_stem(word).endswith("ه")


def test_forms_of_one_word_meet() -> None:
    forms = ["القانون", "قانون", "للقانون", "والقانون", "بالقانون"]
    assert {light_stem(w) for w in forms} == {"قان"}


def test_darija_prefix_meets_the_article_word() -> None:
    """The Darija question "شكون اللي عندو الحق فالحضانة" now meets the word of المادة 171."""
    assert light_stem(normalize_ar("فالحضانة")) == light_stem(normalize_ar("الحضانة"))


@pytest.mark.parametrize("word", ["عليها", "عليهم"])
def test_stemming_does_not_bring_back_stopwords(word: str) -> None:
    assert light_stem(word) in STOPWORDS  # stemming makes it علي ...
    assert tokenize(word) == []  # ... so tokenize drops it again
