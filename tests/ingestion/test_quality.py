"""Tests for page text quality assessment (P1-08, T8, T9, §6.2)."""

from __future__ import annotations

import unicodedata

from src.ingestion.quality import (
    PRESENTATION_FORMS,
    passes_quality_check,
    share_in_ranges,
    share_of_reversed_words,
)


def test_passes_quality_check_normal_arabic() -> None:
    """Standard Arabic legal text exceeding min_letters passes quality check."""
    text = (
        "يطلق على هذا القانون اسم مدونة الأسرة، ويشار إليها بعده باسم المدونة. "
        "تسري أحكام هذه المدونة على جميع المغاربة ولو كانوا مقيمين خارج أرض الوطن."
    )
    assert passes_quality_check(text, min_letters=50) is True


def test_passes_quality_check_too_few_letters() -> None:
    """Page with fewer than min_letters alphabetic characters fails."""
    text = "المادة 1\n12345"
    assert passes_quality_check(text, min_letters=50) is False


def test_passes_quality_check_presentation_forms_raw() -> None:
    """Raw presentation forms exceeding 5% fail quality check (T8 raw)."""
    # U+FE8D is ARABIC LETTER ALEF ISOLATED FORM
    # U+FEDF is ARABIC LETTER LAM ISOLATED FORM
    # U+FEE3 is ARABIC LETTER MEEM ISOLATED FORM
    # U+FE8E is ARABIC LETTER ALEF FINAL FORM
    # U+FEA7 is ARABIC LETTER DAL ISOLATED FORM
    # U+FE93 is ARABIC LETTER TEH MARBUTA ISOLATED FORM
    pres_word = "\ufe8d\ufedf\ufee3\ufe8e\ufea7\ufe93"  # المادة in presentation forms
    raw_text = (pres_word + " ") * 10
    assert share_in_ranges(raw_text, PRESENTATION_FORMS) > 0.05
    assert passes_quality_check(raw_text, min_letters=20) is False


def test_t8_presentation_forms_nfkc_logical_vs_visual() -> None:
    """T8: Logical order presentation forms pass after NFKC, visual reversed forms fail."""
    # 1. Logical order presentation forms: NFKC converts to base letters and passes
    pres_logical = (
        "\ufe8d\ufedf\ufee3\ufe8e\ufea7\ufe93 1 "  # المادة 1
        "تسري أحكام هذا القانون على جميع المواطنين المغاربة في كل مكان وحيثما وجدوا."
    )
    normalized = unicodedata.normalize("NFKC", pres_logical)
    assert passes_quality_check(normalized, min_letters=50) is True

    # 2. Visual reversed order: e.g. ةداملا instead of المادة
    reversed_words = (
        "ةداملا 12 نم اذه نوناقلا ىلع عيمج ةبراغملا يف لك ناكم ثيحو اودجو " "لصفلا 3 مسقلا باتكلا"
    )
    norm_reversed = unicodedata.normalize("NFKC", reversed_words)
    assert share_of_reversed_words(norm_reversed) > 0.3
    assert passes_quality_check(norm_reversed, min_letters=50) is False


def test_t9_reversed_words_fails() -> None:
    """T9: Text containing reversed frequent legal words fails quality check."""
    text = "ةداملا 12 نم اذه نوناقلا ىلع عيمج نينطاوملا يف فلملا اذه"
    assert share_of_reversed_words(text) > 0.3
    assert passes_quality_check(text, min_letters=20) is False


def test_share_of_reversed_words_empty_or_normal() -> None:
    """Normal legal text has 0% reversed words; empty text has 0%."""
    assert share_of_reversed_words("") == 0.0
    normal = "المادة 1 تسري أحكام هذا القانون على جميع المغاربة في كل مكان."
    assert share_of_reversed_words(normal) == 0.0
