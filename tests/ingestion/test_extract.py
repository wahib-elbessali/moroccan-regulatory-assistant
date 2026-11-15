"""Tests for extraction engine and format parsers (P1-06 à P1-14, T8, T10b, T10c, T14, T18)."""

from __future__ import annotations

from pathlib import Path

import docx
import pymupdf
import pytest
from PIL import Image

from src.core.contracts.errors import InvalidInput
from src.core.contracts.fakes.llm import FakeOCRClient
from src.ingestion.extract import extract, sanitize_text
from src.ingestion.models import Page
from src.ingestion.ocr_clean import remove_headers_footers
from tests.ingestion.doubles import LECTEUR_ID, ScriptedOCRClient


def _create_sample_pdf(
    path: Path,
    pages_text: list[str],
    encrypted: bool = False,
    password: str = "secret",
) -> None:
    """Helper to build digital test PDFs with PyMuPDF."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 50), text)
    if encrypted:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password)
    else:
        doc.save(str(path))
    doc.close()


def test_extract_unsupported_format(tmp_path: Path) -> None:
    """P1-06, §7: Unknown extensions raise InvalidInput('unsupported format')."""
    bad_file = tmp_path / "document.xyz"
    bad_file.write_text("dummy", encoding="utf-8")

    with pytest.raises(InvalidInput) as exc_info:
        extract(bad_file)
    assert exc_info.value.message == "unsupported format"


def test_extract_corrupt_pdf(tmp_path: Path) -> None:
    """§7: Corrupt PDF files raise InvalidInput('cannot open file')."""
    corrupt_file = tmp_path / "corrupted.pdf"
    corrupt_file.write_bytes(b"%PDF-1.4 truncated corrupted garbage")

    with pytest.raises(InvalidInput) as exc_info:
        extract(corrupt_file)
    assert exc_info.value.message == "cannot open file"


def test_extract_encrypted_pdf(tmp_path: Path) -> None:
    """§7: Password-protected/encrypted PDF raises InvalidInput('cannot open file')."""
    enc_file = tmp_path / "protected.pdf"
    _create_sample_pdf(enc_file, ["Confidential page"], encrypted=True)

    with pytest.raises(InvalidInput) as exc_info:
        extract(enc_file)
    assert exc_info.value.message == "cannot open file"


def test_extract_digital_pdf(tmp_path: Path) -> None:
    """P1-07: Digital PDFs are extracted page-by-page preserving 1-based page numbers."""
    pdf_file = tmp_path / "digital.pdf"
    p1 = (
        "This is a digital page with more than fifty Latin alphabetic characters "
        "to satisfy the minimum letters per page requirement."
    )
    p2 = (
        "This is the second digital page containing sufficient text content "
        "for digital verification without triggering OCR fallback."
    )
    _create_sample_pdf(pdf_file, [p1, p2])

    pages = extract(pdf_file, ocr_client=FakeOCRClient())
    assert len(pages) == 2
    assert pages[0].number == 1
    assert pages[0].ocr is False
    assert pages[0].confidence is None
    assert "digital page with more than fifty" in pages[0].text
    assert pages[1].number == 2
    assert pages[1].ocr is False


def test_extract_scanned_pdf_triggers_ocr(tmp_path: Path) -> None:
    """P1-08, P1-09: Scanned/empty page triggers OCR through OCRClient."""
    pdf_file = tmp_path / "scanned.pdf"
    # Create empty page (zero letters)
    _create_sample_pdf(pdf_file, [""])

    ocr = ScriptedOCRClient(default_text="نص مستخرج عبر التعرف الضوئي", default_confidence=0.92)
    pages = extract(pdf_file, ocr_client=ocr)

    assert len(pages) == 1
    assert pages[0].number == 1
    assert pages[0].ocr is True
    assert pages[0].confidence == 0.92
    assert pages[0].text == "نص مستخرج عبر التعرف الضوئي"
    assert ocr.call_count == 1


def test_t10c_tiff_multipage_ocr(tmp_path: Path) -> None:
    """T10c: Multi-page TIFF (3 frames) yields 3 pages and calls OCR 3 times."""
    tiff_file = tmp_path / "multipage.tif"
    frames = [
        Image.new("RGB", (60, 60), color=(255, 255, 255)),
        Image.new("RGB", (60, 60), color=(200, 200, 200)),
        Image.new("RGB", (60, 60), color=(150, 150, 150)),
    ]
    frames[0].save(
        str(tiff_file),
        save_all=True,
        append_images=frames[1:],
        format="TIFF",
    )

    ocr = ScriptedOCRClient(default_text="إطار وثيقة", default_confidence=0.95)
    pages = extract(tiff_file, ocr_client=ocr)

    assert len(pages) == 3
    assert [p.number for p in pages] == [1, 2, 3]
    assert all(p.ocr is True for p in pages)
    assert ocr.call_count == 3


def test_t10b_extract_image_direct_ocr(tmp_path: Path) -> None:
    """P1-06b, T10b: Standalone images go directly to OCR without quality check."""
    png_file = tmp_path / "photo.png"
    img = Image.new("RGB", (50, 50), color=(255, 255, 255))
    img.save(str(png_file), format="PNG")

    ocr = ScriptedOCRClient(default_text="صورة مستند", default_confidence=0.88)
    pages = extract(png_file, ocr_client=ocr)

    assert len(pages) == 1
    assert pages[0].number == 1
    assert pages[0].ocr is True
    assert pages[0].confidence == 0.88
    assert ocr.call_count == 1


def test_t14_upload_limit_exceeded_before_extra_ocr_call(tmp_path: Path) -> None:
    """P1-10, T14: Upload exceeding max_pages_upload raises InvalidInput before extra call."""
    pdf_file = tmp_path / "three_scanned.pdf"
    _create_sample_pdf(pdf_file, ["", "", ""])

    ocr = ScriptedOCRClient(default_text="نص", default_confidence=0.9)

    # Allow at most 2 scanned pages for private upload
    with pytest.raises(InvalidInput) as exc_info:
        extract(
            pdf_file,
            owner_id=LECTEUR_ID,
            ocr_client=ocr,
            max_pages_upload=2,
            min_letters_per_page=50,
        )

    assert exc_info.value.message == "too many scanned pages"
    # Verified: stopped before exceeding call limit (called at most limit times)
    assert ocr.call_count == 2


def test_extract_ocr_quality_too_low(tmp_path: Path) -> None:
    """P1-14: If average OCR confidence is below threshold, fails document."""
    pdf_file = tmp_path / "low_conf.pdf"
    _create_sample_pdf(pdf_file, ["", ""])

    ocr = ScriptedOCRClient(responses=[("نص 1", 0.40), ("نص 2", 0.50)])

    with pytest.raises(InvalidInput) as exc_info:
        extract(
            pdf_file,
            ocr_client=ocr,
            ocr_min_confidence=0.60,
            min_letters_per_page=50,
        )

    assert exc_info.value.message == "OCR quality too low"


def test_extract_single_low_confidence_page_kept(tmp_path: Path) -> None:
    """P1-14: Individual low-confidence page is kept if average meets threshold."""
    pdf_file = tmp_path / "mixed_conf.pdf"
    _create_sample_pdf(pdf_file, ["", ""])

    # Average: (0.40 + 0.90) / 2 = 0.65 >= 0.60
    ocr = ScriptedOCRClient(responses=[("نص ضعيف", 0.40), ("نص ممتاز", 0.90)])

    pages = extract(
        pdf_file,
        ocr_client=ocr,
        ocr_min_confidence=0.60,
        min_letters_per_page=50,
    )

    assert len(pages) == 2
    assert pages[0].confidence == 0.40
    assert pages[1].confidence == 0.90


def test_extract_docx(tmp_path: Path) -> None:
    """P1-06: DOCX paragraphs and tables extracted with ' | ' cell separator."""
    doc_file = tmp_path / "test.docx"
    doc = docx.Document()
    doc.add_paragraph("الفقرة الأولى من القرار")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "العمود الأول"
    table.rows[0].cells[1].text = "العمود الثاني"
    doc.save(str(doc_file))

    pages = extract(doc_file)
    assert len(pages) == 1
    assert pages[0].number == 1
    assert "الفقرة الأولى من القرار" in pages[0].text
    assert "العمود الأول | العمود الثاني" in pages[0].text


def test_extract_html(tmp_path: Path) -> None:
    """P1-06: HTML scripts, navigation, style, and footer are stripped."""
    html_file = tmp_path / "test.html"
    html_content = """
    <html>
      <head>
        <style>body { font-size: 14px; }</style>
        <script>console.log("injection");</script>
      </head>
      <body>
        <nav><a href="/">الرئيسية</a></nav>
        <h1>نص الظهير الشريف</h1>
        <p>مقتضيات تنظيمية هامة.</p>
        <footer>حقوق النشر 2026</footer>
      </body>
    </html>
    """
    html_file.write_text(html_content, encoding="utf-8")

    pages = extract(html_file)
    assert len(pages) == 1
    assert "نص الظهير الشريف" in pages[0].text
    assert "مقتضيات تنظيمية هامة." in pages[0].text
    assert "console.log" not in pages[0].text
    assert "الرئيسية" not in pages[0].text
    assert "حقوق النشر" not in pages[0].text


def test_extract_markdown(tmp_path: Path) -> None:
    """P1-06: Markdown strips line-starting hashes, keeping links and code blocks."""
    md_file = tmp_path / "test.md"
    content = (
        "# عنوان رئيسي\n## عنوان فرعي\nنص عادي مع [رابط](http://example.ma)\n```python\nx = 1\n```"
    )
    md_file.write_text(content, encoding="utf-8")

    pages = extract(md_file)
    assert len(pages) == 1
    assert pages[0].text.startswith("عنوان رئيسي\nعنوان فرعي")
    assert "[رابط](http://example.ma)" in pages[0].text
    assert "```python" in pages[0].text


def test_extract_txt_encodings(tmp_path: Path) -> None:
    """P1-06: TXT reads utf-8-sig then falls back to cp1256."""
    utf8_file = tmp_path / "utf8.txt"
    utf8_file.write_text("نص عربي بصيغة يو تي إف", encoding="utf-8-sig")

    pages_utf8 = extract(utf8_file)
    assert pages_utf8[0].text == "نص عربي بصيغة يو تي إف"

    cp1256_file = tmp_path / "cp1256.txt"
    text_ar = "نص عربي بنظام ويندوز القديم"
    cp1256_file.write_bytes(text_ar.encode("cp1256"))

    pages_cp = extract(cp1256_file)
    assert pages_cp[0].text == text_ar


def test_remove_headers_footers_repeated_lines() -> None:
    """P1-12: Header with variable page numbers removed; headings never removed."""
    pages = [
        Page(number=1, text="عدد 7435 ... ص 12\nالمادة 1\nنص المادة الأولى من القانون.\n12"),
        Page(number=2, text="عدد 7435 ... ص 13\nالمادة 2\nنص المادة الثانية من القانون.\n13"),
        Page(number=3, text="عدد 7435 ... ص 14\nالمادة 3\nنص المادة الثالثة من القانون.\n14"),
    ]

    cleaned = remove_headers_footers(pages)
    assert len(cleaned) == 3

    for p in cleaned:
        assert "عدد 7435" not in p.text  # Header pattern removed
        assert not p.text.endswith("12")  # Number-only line removed
        assert not p.text.endswith("13")
        assert not p.text.endswith("14")

    # Headings are preserved
    assert "المادة 1" in cleaned[0].text
    assert "المادة 2" in cleaned[1].text
    assert "المادة 3" in cleaned[2].text


def test_remove_headers_footers_number_only_middle_preserved() -> None:
    """Number-only lines in the middle of page body are preserved; bottom line removed."""
    page_text = (
        "بداية النص القانوني\n"
        "المادة 1\n"
        "1\n"
        "نص البند الأول\n"
        "2\n"
        "نص البند الثاني\n"
        "خاتمة الفقرة هنا\n"
        "12"
    )
    pages = [Page(number=1, text=page_text)]
    cleaned = remove_headers_footers(pages)
    assert len(cleaned) == 1
    lines = cleaned[0].text.splitlines()
    assert "1" in lines
    assert "2" in lines
    assert "12" not in lines


def test_remove_headers_footers_alternating_headers() -> None:
    """6-page PDF with header A on odd pages and B on even pages: both removed, heading preserved."""
    pages = [
        Page(number=1, text="الجريدة الرسمية عدد 7400\nالمادة 1\nنص المادة الأولى من القانون."),
        Page(number=2, text="المملكة المغربية - الأمانة العامة\nنص إضافي في الصفحة الثانية."),
        Page(number=3, text="الجريدة الرسمية عدد 7400\nنص إضافي في الصفحة الثالثة."),
        Page(number=4, text="المملكة المغربية - الأمانة العامة\nنص إضافي في الصفحة الرابعة."),
        Page(number=5, text="الجريدة الرسمية عدد 7400\nنص إضافي في الصفحة الخامسة."),
        Page(number=6, text="المملكة المغربية - الأمانة العامة\nنص إضافي في الصفحة السادسة."),
    ]
    cleaned = remove_headers_footers(pages)
    assert len(cleaned) == 6
    for p in cleaned:
        assert "الجريدة الرسمية عدد 7400" not in p.text
        assert "المملكة المغربية - الأمانة العامة" not in p.text
    assert "المادة 1" in cleaned[0].text


def test_remove_headers_footers_internal_doc_notice() -> None:
    """P1-12: The internal doc notice on page 1 is preserved once."""
    notice = "وثيقة تجريبية — محتوى خيالي"
    pages = [
        Page(number=1, text=f"{notice}\nالمادة 1\nنص تنظيمي"),
        Page(number=2, text=f"{notice}\nالمادة 2\nنص تنظيمي إضافي"),
        Page(number=3, text=f"{notice}\nالمادة 3\nنص تنظيمي ختامي"),
    ]

    cleaned = remove_headers_footers(pages)
    assert notice in cleaned[0].text
    assert notice not in cleaned[1].text
    assert notice not in cleaned[2].text


def test_t18_no_document_text_in_errors(tmp_path: Path) -> None:
    """T18: No document text leaks into error messages or exception strings."""
    # Test all failure paths
    secret_text = "SECRET_DOCUMENT_CONTENT_DO_NOT_LEAK"

    # Unsupported format
    unsupported = tmp_path / "secret.xyz"
    unsupported.write_text(secret_text, encoding="utf-8")
    with pytest.raises(InvalidInput) as exc:
        extract(unsupported)
    assert secret_text not in str(exc.value)
    assert exc.value.message == "unsupported format"

    # Corrupted file
    corrupt = tmp_path / "secret.pdf"
    corrupt.write_bytes(f"%PDF-1.4 {secret_text}".encode())
    with pytest.raises(InvalidInput) as exc:
        extract(corrupt)
    assert secret_text not in str(exc.value)
    assert exc.value.message == "cannot open file"


def test_integration_real_public_pdf() -> None:
    """Read-only test on a small real PDF from data/raw/public if available."""
    real_pdf = Path("data/raw/public/adala_001.pdf")
    if not real_pdf.is_file():
        pytest.skip("data/raw/public/adala_001.pdf not present in workspace")

    pages = extract(real_pdf, ocr_client=FakeOCRClient())
    assert len(pages) > 0
    assert pages[0].number == 1


def test_sanitize_text_strips_cc_control_characters() -> None:
    """Sanitize Unicode Cc control characters (e.g. \\x08) while preserving \\n and \\t."""
    # Text with \x08 inside word, at end of line, with tab and newline
    raw = "المادة\x08 1\nنص تنظيمي مفصل\x08\nفقرة جديدة\tمع تفاصيل: 100%."
    sanitized = sanitize_text(raw)

    assert "\x08" not in sanitized
    assert sanitized == "المادة 1\nنص تنظيمي مفصل\nفقرة جديدة\tمع تفاصيل: 100%."

    # Normal Arabic text without control characters remains completely untouched
    arabic_clean = "ظهير شريف رقم 1.23.45 صادر في 15 من شعبان 1445 (26 فبراير 2024)"
    assert sanitize_text(arabic_clean) == arabic_clean


def test_extract_digital_pdf_sanitizes_control_characters(tmp_path: Path) -> None:
    """extract() strips \\x08 and other Cc chars from digital PDF, preserving \\n."""
    pdf_file = tmp_path / "control_chars.pdf"
    content = (
        "Article\x08 1: Digital regulatory text with sufficient character length\n"
        "to satisfy the minimum letters per page requirement without OCR.\n"
        "Second line with a control character at the end\x08\n"
        "and a final paragraph with normal punctuation."
    )
    _create_sample_pdf(pdf_file, [content])

    pages = extract(pdf_file, ocr_client=FakeOCRClient())
    assert len(pages) == 1
    assert pages[0].ocr is False
    assert "\x08" not in pages[0].text
    assert "Article 1:" in pages[0].text
    assert "Second line with a control character at the end\n" in pages[0].text
    assert "\n" in pages[0].text


def test_extract_txt_sanitizes_control_characters(tmp_path: Path) -> None:
    """extract() strips \\x08 from TXT files while preserving \\n, \\t, and Arabic text."""
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text(
        "المادة\x08 1\nنص المادة الأولى من القانون التنظيمي\x08\nبند إضافي\tتفاصيل: 42.",
        encoding="utf-8",
    )

    pages = extract(txt_file)
    assert len(pages) == 1
    assert "\x08" not in pages[0].text
    assert pages[0].text == "المادة 1\nنص المادة الأولى من القانون التنظيمي\nبند إضافي\tتفاصيل: 42."


def test_extract_ocr_sanitizes_control_characters(tmp_path: Path) -> None:
    """extract() strips \\x08 and Cc chars from OCR fallback text."""
    pdf_file = tmp_path / "scanned_ctrl.pdf"
    _create_sample_pdf(pdf_file, [""])  # empty page triggers OCR

    ocr = ScriptedOCRClient(
        default_text="المادة\x08 1\nنص مستخرج عبر التعرف الضوئي\x08\nتفاصيل\tإضافية.",
        default_confidence=0.95,
    )
    pages = extract(pdf_file, ocr_client=ocr)
    assert len(pages) == 1
    assert pages[0].ocr is True
    assert "\x08" not in pages[0].text
    assert "المادة 1" in pages[0].text
    assert "\n" in pages[0].text


def test_integration_real_sgg_7435_no_control_characters() -> None:
    """Real PDF sgg_7435.pdf containing raw \\x08 in headers is sanitized cleanly."""
    real_pdf = Path("data/raw/public/sgg_7435.pdf")
    if not real_pdf.is_file():
        pytest.skip("data/raw/public/sgg_7435.pdf not present in workspace")

    pages = extract(real_pdf, ocr_client=FakeOCRClient())
    for page in pages:
        assert "\x08" not in page.text
