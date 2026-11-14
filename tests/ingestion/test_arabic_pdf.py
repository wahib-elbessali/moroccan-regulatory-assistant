"""Unit tests for Arabic PDF ligature correction (Étape 1)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from src.ingestion.arabic_pdf import (
    extract_digital_pdf_pages,
    fix_inverted_headings,
    fix_span_ligatures,
    is_arabic_letter,
)
from src.ingestion.chunking import chunk_document
from src.ingestion.extract import extract


def test_is_arabic_letter() -> None:
    """Verifies that is_arabic_letter only matches Arabic alphabetic letters."""
    assert is_arabic_letter("ا") is True
    assert is_arabic_letter("ل") is True
    assert is_arabic_letter("م") is True
    assert is_arabic_letter("ة") is True

    # Combining marks (fatha, damma, shadda) are NOT letters
    assert is_arabic_letter("\u064e") is False  # Fatha (Mn)
    assert is_arabic_letter("\u0651") is False  # Shadda (Mn)

    # Spaces, digits, Latin, punctuation
    assert is_arabic_letter(" ") is False
    assert is_arabic_letter("1") is False
    assert is_arabic_letter("a") is False
    assert is_arabic_letter(".") is False


def test_fix_span_ligatures_group_of_two() -> None:
    """Reverses 2-letter ligature with leading zero-width Arabic letter ('املادة' -> 'المادة')."""
    # 'ا' (normal width), 'م' (zero width), 'ل' (normal width), 'ا', 'د', 'ة'
    chars = [
        ("ا", 0.0, 3.0),
        ("م", 3.0, 3.0),  # zero width
        ("ل", 3.0, 7.0),  # normal width
        ("ا", 7.0, 10.0),
        ("د", 10.0, 14.0),
        ("ة", 14.0, 18.0),
    ]
    result = fix_span_ligatures(chars)
    assert result == "المادة"


def test_fix_span_ligatures_group_of_four() -> None:
    """Reverses 4-letter ligature with 3 leading zero-width Arabic letters."""
    # Letters: 'د' (0w), 'ج' (0w), 'ب' (0w), 'أ' (normal width) -> should become 'أ' + 'ب' + 'ج' + 'د'
    chars = [
        ("د", 0.0, 0.0),
        ("ج", 0.0, 0.0),
        ("ب", 0.0, 0.0),
        ("أ", 0.0, 5.0),
    ]
    result = fix_span_ligatures(chars)
    assert result == "أبجد"


def test_combining_mark_never_moved() -> None:
    """Short vowels and combining marks (Mn) are never displaced by ligature reversal."""
    # 'م' (0w), 'َ' (fatha Mn, 0w), 'ل' (normal width)
    # The fatha is NOT an Arabic letter, so it does not participate in ligature reversal
    chars = [
        ("م", 0.0, 0.0),
        ("\u064e", 0.0, 0.0),  # Fatha
        ("ل", 0.0, 4.0),
    ]
    result = fix_span_ligatures(chars)
    # 'م' stays, fatha stays, 'ل' stays (not an Arabic letter group because broken by mark)
    assert "\u064e" in result


def test_space_never_moved() -> None:
    """Spaces are never included in ligature groups or displaced."""
    chars = [
        ("م", 0.0, 0.0),
        (" ", 0.0, 3.0),
        ("ل", 3.0, 7.0),
    ]
    result = fix_span_ligatures(chars)
    assert result == "م ل"


def test_healthy_document_selection_keeps_raw(tmp_path: Path) -> None:
    """A healthy document without reversed ligature artifacts selects the raw variant."""
    pdf_path = tmp_path / "healthy.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(
        (50, 50),
        "Kingdom of Morocco - Healthy Document without ligature issues.",
    )
    doc.save(str(pdf_path))
    doc.close()

    check_doc = pymupdf.open(str(pdf_path))
    pages, variant, stats = extract_digital_pdf_pages(check_doc)
    check_doc.close()

    assert variant == "raw"
    assert stats["diff"] == 0
    assert "Kingdom of Morocco" in pages[0]


def test_internal_document_keeps_raw() -> None:
    """internal_01_ai_governance.pdf is a healthy document and must select the raw variant."""
    path = Path("data/raw/internal/internal_01_ai_governance.pdf")
    if not path.is_file():
        pytest.skip("internal_01_ai_governance.pdf not present")

    doc = pymupdf.open(str(path))
    _, variant, stats = extract_digital_pdf_pages(doc)
    doc.close()

    assert variant == "raw"
    assert stats["raw_impossible"] == 0
    assert stats["corrected_impossible"] == 0


def test_sgg_7435_page_4_regression() -> None:
    """Regression test on sgg_7435.pdf page 4: contains 'المادة الأولى' and no 'املادة'."""
    path = Path("data/raw/public/sgg_7435.pdf")
    if not path.is_file():
        pytest.skip("sgg_7435.pdf not present")

    doc = pymupdf.open(str(path))
    pages, variant, stats = extract_digital_pdf_pages(doc)
    doc.close()

    assert variant == "corrected"
    assert stats["raw_impossible"] > stats["corrected_impossible"]
    assert stats["diff"] >= 3

    page_4_text = pages[3]  # Page 4 (0-indexed 3)
    assert "المادة الأولى" in page_4_text
    assert "املادة" not in page_4_text


def test_fix_inverted_headings_required_cases() -> None:
    """Explicit test cases: reverses inverted headings into logical Arabic order."""
    assert fix_inverted_headings("2 المادة") == "المادة 2"
    assert fix_inverted_headings("12 مكرر المادة") == "المادة 12 مكرر"
    assert fix_inverted_headings("الأولى المادة") == "المادة الأولى"

    # Additional legal title words and numerals
    assert fix_inverted_headings("2 الفصل") == "الفصل 2"
    assert fix_inverted_headings("1 الباب") == "الباب 1"
    assert fix_inverted_headings("3 القسم") == "القسم 3"
    assert fix_inverted_headings("4 الفرع") == "الفرع 4"
    assert fix_inverted_headings("5 الكتاب") == "الكتاب 5"
    assert fix_inverted_headings("الثانية المادة") == "المادة الثانية"
    assert fix_inverted_headings("مكرر 12 المادة") == "المادة 12 مكرر"


def test_fix_inverted_headings_invariants() -> None:
    """Lines already in correct order, with surrounding text, or unsupported words are never modified."""
    assert fix_inverted_headings("المادة 2") == "المادة 2"
    assert fix_inverted_headings("من 2 المادة التالية") == "من 2 المادة التالية"
    assert fix_inverted_headings("2 كتاب") == "2 كتاب"
    assert fix_inverted_headings("المادة 12 مكرر") == "المادة 12 مكرر"
    assert fix_inverted_headings("المادة الأولى") == "المادة الأولى"


def test_sgg_7412_chunker_headings_substantially_increased() -> None:
    """Read-only test on sgg_7412.pdf: chunker detected headings jump from 4 to over 100."""
    pdf_path = Path("data/raw/public/sgg_7412.pdf")
    if not pdf_path.is_file():
        pytest.skip("sgg_7412.pdf not present in data/raw/public/")

    pages = extract(pdf_path)
    chunks = chunk_document("sgg_7412", pages)

    headings = {c.article for c in chunks if c.article is not None}
    # Before the fix, only 3 distinct headings (4 occurrences) were detected
    # With inverted headings reordered, 171 distinct headings are identified
    assert len(headings) > 100
    assert "المادة 2" in headings
    assert "المادة 3" in headings
    assert "المادة 10" in headings
