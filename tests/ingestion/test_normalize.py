"""Acceptance and unit tests for Arabic text normalization (P1-15, P1-16, P1-17).

Covers acceptance tests T6, T7 and extensive edge cases:
- Empty and whitespace-only strings
- Invisible format characters removal (Unicode category Cf: RLM, LRM, ZWNJ, ZWJ, BOM, ALM, SHY)
- Arabic-Indic and Persian digits
- Arabic punctuation (، ؛ ؟) and symbols
- Arabic presentation forms (U+FB50–U+FDFF, U+FE70–U+FEFF)
- Mixed Arabic and French legal text
- Multiple spaces, newlines, and tabs
- Verified real articles from the public corpus
- Non-stemming preservation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.normalize import normalize_ar

# --- T6: Acceptance test from P1 spec §8 --------------------------------------------------------


@pytest.mark.parametrize(
    "input_text, expected",
    [
        ("الْمَادَّةُ", "الماده"),
        ("أحكام", "احكام"),
        ("مسؤولية", "مسؤوليه"),
        ("١٢", "12"),
        ("ـــالقانون", "القانون"),
        ("المادة\u200f", "الماده"),  # "المادة" followed by U+200F (RLM)
    ],
)
def test_acceptance_t6_rules(input_text: str, expected: str) -> None:
    """T6: Verifies each of the key normalization transformations required by the spec."""
    assert normalize_ar(input_text) == expected


# --- T7: Idempotence test from P1 spec §8 (P1-17) ----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\t\n\r",
        "المملكة المغربية",
        "الْمَادَّةُ ١٢: تُطَبَّقُ الْأَحْكَامُ.",
        "Code de la famille — مدونة الأسرة رقم 70.03",
        "ـــقانونـــ",
        "٠١٢٣٤٥٦٧٨٩ ۰۱۲۳۴۵۶۷۸۹ 0123456789",
        "،؛؟.!?:;-«»()[]{}",
        "ﭐ ﭤ ﭥ ﭦ ﭧ ﭨ",  # Presentation forms A
        "ﺀ ﺁ ﺂ ﺃ ﺄ ﺅ ﺆ ﺇ ﺈ ﺉ ﺊ ﺋ ﺌ",  # Presentation forms B
        "المادة 12: تطبق على عقد الزواج المشوب بإكراه أو تدليس الأحكام المنصوص عليها.",
        "المادة\u200f 12\u200e \u200cالقانون\u200d \ufeffالمغربي\u061c \u00adالرسمي",
    ],
)
def test_acceptance_t7_idempotence(text: str) -> None:
    """T7: normalize_ar(normalize_ar(x)) == normalize_ar(x) for any string."""
    first_pass = normalize_ar(text)
    second_pass = normalize_ar(first_pass)
    assert second_pass == first_pass


# --- Rule 2: Invisible format characters (Unicode category Cf) --------------------------------


def test_invisible_format_characters_removal() -> None:
    """Verifies that all invisible format characters (Unicode category Cf) are removed."""
    # RLM (U+200F), LRM (U+200E)
    assert normalize_ar("المادة\u200f 12") == "الماده 12"
    assert normalize_ar("المادة\u200e 12") == "الماده 12"
    assert normalize_ar("المادة\u200f 12") == normalize_ar("المادة 12")

    # ZWNJ (U+200C), ZWJ (U+200D)
    assert normalize_ar("مقتض\u200cيات") == "مقتضيات"
    assert normalize_ar("الـ\u200dقانون") == "القانون"

    # BOM / Zero Width No-Break Space (U+FEFF)
    assert normalize_ar("\ufeffالمملكة المغربية\ufeff") == "المملكه المغربيه"

    # Arabic Letter Mark (ALM, U+061C)
    assert normalize_ar("فصل\u061c 5") == "فصل 5"

    # Soft Hyphen (SHY, U+00AD)
    assert normalize_ar("مسؤولـ\u00adـية") == "مسؤوليه"

    # Mixed invisible format characters inside a sentence
    dirty = "\ufeffالمادة\u200f 12:\u200e تطبق\u061c مقتض\u200cيات\u200d هذا\u00ad القانون."
    clean = "المادة 12: تطبق مقتضيات هذا القانون."
    assert normalize_ar(dirty) == normalize_ar(clean)


# --- Edge cases: Empty and whitespace -----------------------------------------------------------


def test_empty_and_whitespace_strings() -> None:
    assert normalize_ar("") == ""
    assert normalize_ar("   ") == ""
    assert normalize_ar("\n\t\r  \n  \t") == ""


# --- Edge cases: Digits (Rule 8) ---------------------------------------------------------------


def test_arabic_indic_and_persian_digits() -> None:
    # Arabic-Indic: ٠١٢٣٤٥٦٧٨٩
    assert normalize_ar("المادة ٠١٢٣٤٥٦٧٨٩") == "الماده 0123456789"
    # Persian: ۰۱۲۳۴۵۶۷۸۹
    assert normalize_ar("الفصل ۰۱۲۳۴۵۶۷۸۹") == "الفصل 0123456789"
    # Mixed digits in legal numbers
    assert normalize_ar("القانون رقم ٧٠.۰۳") == "القانون رقم 70 03"


# --- Edge cases: Punctuation and symbols (Rule 10) ----------------------------------------------


def test_arabic_punctuation_and_symbols() -> None:
    # Arabic comma, semicolon, question mark
    assert normalize_ar("، ؛ ؟") == ""
    assert normalize_ar("حقوق، التزامات؛ فما هي العقوبات؟") == "حقوق التزامات فما هي العقوبات"

    # Latin and common legal symbols: §, °, «, », -, /, :, etc.
    legal_text = "Dahir n° 1-58-250 § 3: « أحكام عامة / خاصة »"
    expected = "dahir n 1 58 250 3 احكام عامه خاصه"
    assert normalize_ar(legal_text) == expected


# --- Edge cases: Arabic Presentation Forms (Rule 1) --------------------------------------------


def test_arabic_presentation_forms() -> None:
    # U+FE8E (Alef final), U+FE87 (Alef with hamza below isolated), U+FE93 (Teh marbuta isolated)
    # U+FC32 (Ligature feh with yeh isolated)
    pres_forms = "\ufe8e \ufe87 \ufe93 \ufc32"
    assert normalize_ar(pres_forms) == "ا ا ه في"


# --- Edge cases: Alef variants and Alef Wasla (Rule 5) -----------------------------------------


def test_alef_variants_normalization() -> None:
    # أ, إ, آ, ٱ all become ا
    variants = "أحمد إبراهيم آمنة ٱمرأة"
    assert normalize_ar(variants) == "احمد ابراهيم امنه امراه"


# --- Edge cases: Alif Maqsura and Teh Marbuta (Rules 6 and 7) ----------------------------------


def test_alif_maqsura_and_teh_marbuta() -> None:
    # ى -> ي
    assert normalize_ar("إلى على مستشفى يحيى") == "الي علي مستشفي يحيي"
    # ة -> ه
    assert normalize_ar("محكمة الأسرة بالرباط") == "محكمه الاسره بالرباط"


# --- Edge cases: Tatweel removal (Rule 4) ------------------------------------------------------


def test_tatweel_removal() -> None:
    assert normalize_ar("الــــمــــادّة") == "الماده"
    assert normalize_ar("ـقـانـونـ") == "قانون"


# --- Edge cases: Mixed Arabic and French --------------------------------------------------------


def test_mixed_arabic_and_french() -> None:
    mixed = "Bulletin Officiel الجريدة الرسمية N° 5200 du 24 safar 1425"
    expected = "bulletin officiel الجريده الرسميه n 5200 du 24 safar 1425"
    assert normalize_ar(mixed) == expected


# --- Edge cases: Whitespace collapse (Rule 11) -------------------------------------------------


def test_whitespace_collapsing() -> None:
    text = "   المادة   \t\t 15   \n\n\n  من   القانون   "
    assert normalize_ar(text) == "الماده 15 من القانون"


# --- Requirement P1-16: No stemming -----------------------------------------------------------


def test_no_stemming_performed() -> None:
    """Verifies that words retain their inflections/plurals and are not stemmed."""
    words = "قوانين محاكم يكتبون التزامات مساهمين"
    assert normalize_ar(words) == "قوانين محاكم يكتبون التزامات مساهمين"


# --- Real articles from data/raw/public/ (Read-only verification) ------------------------------


def test_real_articles_from_moudawana() -> None:
    """Tests normalization against exact texts from the official Moroccan Family Code."""
    # Article 3
    art3 = "المادة 3: تعتبر النيابة العامة طرفا أصليا في جميع القضايا الرامية إلى تطبيق أحكام هذه المدونة."
    expected_art3 = "الماده 3 تعتبر النيابه العامه طرفا اصليا في جميع القضايا الراميه الي تطبيق احكام هذه المدونه"
    assert normalize_ar(art3) == expected_art3

    # Article 8
    art8 = (
        "المادة 8: لكل من الخاطب والمخطوبة أن يسترد ما قدمه من هدايا، "
        "ما لم يكن العدول عن الخطبة من قبله."
    )
    expected_art8 = "الماده 8 لكل من الخاطب والمخطوبه ان يسترد ما قدمه من هدايا ما لم يكن العدول عن الخطبه من قبله"
    assert normalize_ar(art8) == expected_art8

    # Article 12
    art12 = (
        "المادة 12: تطبق على عقد الزواج المشوب بإكراه أو تدليس "
        "الأحكام المنصوص عليها في المادتين 63 و 66 بعده."
    )
    expected_art12 = (
        "الماده 12 تطبق علي عقد الزواج المشوب باكراه او تدليس "
        "الاحكام المنصوص عليها في المادتين 63 و 66 بعده"
    )
    assert normalize_ar(art12) == expected_art12


def test_real_pdf_extraction_if_present() -> None:
    """Reads a real page directly from data/raw/public/adala_001.pdf if the file is available."""
    pdf_path = Path("data/raw/public/adala_001.pdf")
    if not pdf_path.exists():
        pytest.skip("adala_001.pdf not present")

    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    # Page 11 contains Article 3
    page_text = doc[10].get_text()
    normalized = normalize_ar(page_text)

    # Basic invariants
    assert "الماده" in normalized
    assert "النيابه العامه" in normalized
    # Idempotence on raw extracted text
    assert normalize_ar(normalized) == normalized
