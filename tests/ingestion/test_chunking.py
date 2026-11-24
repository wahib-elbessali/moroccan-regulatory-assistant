"""Tests for document chunking engine (P1-18 à P1-26, T1 à T5, T19, T21, T23)."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from src.core.contracts.fakes import FakeOCRClient
from src.core.contracts.models import DocumentMeta
from src.ingestion.chunking import (
    _ChunkUnit,
    _is_text_start_line,
    chunk_document,
    heading_word,
    split_long,
    update_path,
)
from src.ingestion.extract import extract
from src.ingestion.models import Page


def test_t1_article_chunking_with_preamble() -> None:
    """T1: Text with preamble and 3 'المادة' headings produces 1 preamble and 3 article chunks."""
    content = (
        "ديباجة القانون التنظيمي ونطاق تطبيقه العام.\n"
        "المادة 1\n"
        "تسري أحكام هذا القانون على كافة المؤسسات.\n"
        "المادة 2\n"
        "تحدد شروط وإجراءات ممارسة الأنشطة المهنية.\n"
        "المادة 3\n"
        "يعاقب كل مخالف للمقتضيات المنصوص عليها."
    )
    pages = [Page(number=1, text=content)]
    meta = DocumentMeta(title="قانون تجريبي", source_file="doc.pdf")

    chunks = chunk_document("doc1", pages, meta=meta)
    assert len(chunks) == 4
    # Preamble chunk
    assert chunks[0].article is None
    assert "ديباجة القانون" in chunks[0].text
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 4

    # 3 Article chunks
    assert chunks[1].article == "المادة 1"
    assert chunks[2].article == "المادة 2"
    assert chunks[3].article == "المادة 3"


def test_t2_fasl_headings_when_no_madda() -> None:
    """T2: Text with 'الفصل' headings and no 'المادة' resolves الفصل as article unit (P1-19)."""
    content = (
        "الفصل 1\n"
        "يحدد هذا القانون قواعد التعاقد المدني.\n"
        "الفصل 2\n"
        "ينشأ العقد بتطابق إيجاب وقبول الطرفين.\n"
        "الفصل 3\n"
        "يبطل الالتزام إذا كان محله مخالفا للنظام العام."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc2", pages)

    assert len(chunks) == 3
    assert chunks[0].article == "الفصل 1"
    assert chunks[1].article == "الفصل 2"
    assert chunks[2].article == "الفصل 3"


def test_t3_hierarchy_stacking() -> None:
    """T3: Headings 'الباب الأول' › 'الفصل الثاني' › 'المادة 5' fill hierarchy correctly."""
    content = (
        "الباب الأول: المبادئ العامة\n"
        "الفصل الثاني: نطاق التطبيق\n"
        "المادة 5\n"
        "تطبق أحكام هذا الباب على جميع المعاملات التجارية."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc3", pages)

    assert len(chunks) == 1
    assert chunks[0].article == "المادة 5"
    assert chunks[0].hierarchy == [
        "الباب الأول: المبادئ العامة",
        "الفصل الثاني: نطاق التطبيق",
    ]


def test_t4_split_long_articles() -> None:
    """T4: An article of 3× max_chunk_chars is split into ≥ 3 chunks with the same article."""
    para = "هذه فقرة قانونية تتضمن شرحا تفصيليا وموسعا لمقتضيات هذه المادة التنظيمية الهامة.\n"
    # Create article text ~ 1500 chars with max_chunk_chars = 400
    body = para * 15
    content = f"المادة 10\n{body}"
    pages = [Page(number=1, text=content)]

    chunks = chunk_document("doc4", pages, max_chunk_chars=400)
    assert len(chunks) >= 3
    for c in chunks:
        assert c.article == "المادة 10"
        assert len(c.text) <= 400


def test_t5_page_boundaries() -> None:
    """T5: An article spanning pages 2–3 sets page_start = 2 and page_end = 3."""
    pages = [
        Page(number=1, text="ديباجة تمهيدية في الصفحة الأولى.\n"),
        Page(number=2, text="المادة 7\nبداية نص المادة السابعة في الصفحة الثانية.\n"),
        Page(number=3, text="تتمة نص المادة السابعة وخاتمتها في الصفحة الثالثة.\n"),
    ]
    chunks = chunk_document("doc5", pages)
    art_chunk = [c for c in chunks if c.article == "المادة 7"][0]

    assert art_chunk.page_start == 2
    assert art_chunk.page_end == 3


def test_t19_chunk_indexes_and_total() -> None:
    """T19: Document giving 4 chunks has chunk_index 0, 1, 2, 3 and total_chunks = 4 on all."""
    content = "المادة 1\nنص 1.\n" "المادة 2\nنص 2.\n" "المادة 3\nنص 3.\n" "المادة 4\nنص 4."
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc19", pages)

    assert len(chunks) == 4
    for idx, c in enumerate(chunks):
        assert c.chunk_index == idx
        assert c.total_chunks == 4


def test_t21_update_path_drops_deeper_levels() -> None:
    """T21: 'الباب الأول' › 'الفصل الأول' › 'المادة 1' › 'الباب الثاني' › 'المادة 2'.

    Article 2 has hierarchy = ['الباب الثاني'] (old 'الفصل الأول' dropped).
    """
    content = (
        "الباب الأول\n"
        "الفصل الأول\n"
        "المادة 1\n"
        "نص المادة الأولى.\n"
        "الباب الثاني\n"
        "المادة 2\n"
        "نص المادة الثانية."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc21", pages)

    assert len(chunks) == 2
    assert chunks[0].article == "المادة 1"
    assert chunks[0].hierarchy == ["الباب الأول", "الفصل الأول"]
    assert chunks[1].article == "المادة 2"
    assert chunks[1].hierarchy == ["الباب الثاني"]


def test_t23_fixed_strategy_sliding_overlap() -> None:
    """T23: ingestion.strategy = fixed, text 3× max_chunk_chars gives ≥ 3 chunks with overlap."""
    words = ["كلمة", "قانونية", "إدارية", "تنظيمية", "مغربية"]
    long_text = " ".join(words * 200)  # ~ 5000 chars

    pages = [Page(number=1, text=long_text)]
    chunks = chunk_document(
        "doc23",
        pages,
        strategy="fixed",
        max_chunk_chars=500,
        overlap_chars=100,
    )

    assert len(chunks) >= 3
    for i in range(len(chunks) - 1):
        assert len(chunks[i].text) <= 500
        # Consecutive chunks share text
        words_cur = set(chunks[i].text.split())
        words_next = set(chunks[i + 1].text.split())
        assert len(words_cur.intersection(words_next)) > 0


def test_isolated_heading_word_fused_with_next_line() -> None:
    """Real case (adala_001 P57/P102): 'المادة' alone on line 1, number on line 2 -> 'المادة 179'."""
    content = (
        "مقدمة سابقة.\n"
        "المادة\n"
        "179\n"
        "تسري أحكام هذه المادة على تصرفات المحجور بعد بلوغه سن الرشد."
    )
    pages = [Page(number=57, text=content)]
    chunks = chunk_document("doc_iso", pages)

    art_chunks = [c for c in chunks if c.article is not None]
    assert len(art_chunks) == 1
    assert art_chunks[0].article == "المادة 179"
    assert "تسري أحكام هذه المادة" in art_chunks[0].text


def test_preliminary_chapter_hierarchy() -> None:
    """'باب تمهيدي' or 'الباب التمهيدي' is recognized as hierarchy level."""
    content = "باب تمهيدي: أحكام عامة\n" "المادة 1\n" "يسمى هذا القانون مدونة التجارة."
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_prelim", pages)

    assert len(chunks) == 1
    assert chunks[0].article == "المادة 1"
    assert chunks[0].hierarchy == ["باب تمهيدي: أحكام عامة"]


def test_unique_article_heading() -> None:
    """'مادة فريدة' or 'المادة الفريدة' is detected as an article."""
    content = (
        "ظهير شريف رقم 1.21.73 بتنفيذ القانون رقم 65.21.\n"
        "المادة الفريدة\n"
        "تغير وتتمم على النحو التالي أحكام المادة 15 من مدونة الأسرة."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_unique", pages)

    art_chunks = [c for c in chunks if c.article is not None]
    assert len(art_chunks) == 1
    assert "المادة الفريدة" in art_chunks[0].article


def test_ordinals_headings() -> None:
    """Explicit ordinals (الأولى, الثانية, الحادية عشرة, مكرر) are matched."""
    content = (
        "المادة الأولى\nنص الأولى.\n"
        "المادة الثانية\nنص الثانية.\n"
        "المادة 13 مكرر\nنص مكرر.\n"
        "المادة 13 مكرر مرتين\nنص مكرر مرتين."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_ord", pages)

    articles = [c.article for c in chunks]
    assert "المادة الأولى" in articles
    assert "المادة الثانية" in articles
    assert "المادة 13 مكرر" in articles
    assert "المادة 13 مكرر مرتين" in articles


def test_cross_reference_citations_not_chunked_as_articles() -> None:
    """Citations ('مع مراعاة أحكام المادة 15 أعلاه') are not treated as article headings."""
    content = (
        "المادة 10\n"
        "تطبق هذه المسطرة مع مراعاة أحكام\n"
        "المادة 15\n"
        "أعلاه في جميع الحالات.\n"
        "المادة 11\n"
        "نص المادة الحادية عشرة."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_cite", pages)

    articles = [c.article for c in chunks if c.article]
    assert "المادة 10" in articles
    assert "المادة 11" in articles
    assert "المادة 15" not in articles  # False positive prevented


def test_chunk_attributes_and_contracts() -> None:
    """Chunk fields conform to Chunk model and P1-24 à P1-26."""
    owner = uuid4()
    meta = DocumentMeta(
        title="مدونة الأسرة",
        source_file="adala.pdf",
        source="https://adala.justice.gov.ma",
        date="2004-02-03",
    )
    pages = [Page(number=1, text="المادة 1\nنص قانوني مغربي.")]

    chunks = chunk_document("doc_meta", pages, owner_id=owner, meta=meta)
    assert len(chunks) == 1
    c = chunks[0]

    assert c.doc_id == "doc_meta"
    assert c.chunk_index == 0
    assert c.total_chunks == 1
    assert c.title == "مدونة الأسرة"
    assert c.source_file == "adala.pdf"
    assert c.source == "https://adala.justice.gov.ma"
    assert c.date == "2004-02-03"
    assert c.owner_id == owner
    assert c.allowed_roles == []
    assert c.language == "ar"
    assert c.text_normalized != ""
    assert c.chunk_id != ""


def test_heading_word_and_update_path() -> None:
    """heading_word extracts level word, update_path maintains hierarchy levels."""
    assert heading_word("الكتاب الأول: التجارة") == "الكتاب"
    assert heading_word("الباب الثاني: العقود") == "الباب"
    assert heading_word("الفصل الأول") == "الفصل"

    path = update_path([], "الكتاب", "الكتاب الأول")
    assert path == ["الكتاب الأول"]
    path = update_path(path, "الباب", "الباب الأول")
    assert path == ["الكتاب الأول", "الباب الأول"]
    path = update_path(path, "الباب", "الباب الثاني")
    assert path == ["الكتاب الأول", "الباب الثاني"]


def test_french_text_no_arabic_headings_has_no_article() -> None:
    """French text without Arabic headings produces chunks with article = None (P1-18)."""
    content = (
        "Article 1\n"
        "La présente loi s'applique aux entreprises marocaines.\n"
        "Article 2\n"
        "Les dispositions du présent dahir sont obligatoires."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_fr", pages)

    assert len(chunks) >= 1
    for c in chunks:
        assert c.article is None


def test_canonical_heading_labels_and_hierarchy() -> None:
    """Headings like 'المادة1' or 'المادة  الأولى' get canonical labels ('المادة 1', 'المادة الأولى').

    The chunk text itself preserves original spacing, and hierarchy labels are also canonicalized.
    """
    content = (
        "الباب1: أحكام أولية\n"
        "المادة1\n"
        "نص المادة 1 كما هو في الأصل مع مسافاته.\n"
        "المادة  الأولى\n"
        "نص المادة الأولى.\n"
        "المادة 13   مكرر\n"
        "نص المادة 13 مكرر."
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_canon", pages)

    assert len(chunks) == 3
    assert chunks[0].article == "المادة 1"
    assert chunks[0].hierarchy == ["الباب 1: أحكام أولية"]
    assert "المادة1\nنص المادة 1 كما هو في الأصل مع مسافاته." in chunks[0].text

    assert chunks[1].article == "المادة الأولى"
    assert chunks[2].article == "المادة 13 مكرر"


def test_trivial_chunks_merged_or_dropped() -> None:
    """Trivial chunks (<3 letters or pure punctuation like '{') are merged into the next chunk.

    Chunk indices and total_chunks remain continuous and accurate (T19).
    """
    content = (
        "{\n"  # Trivial preamble -> should merge into next chunk
        "المادة 1\n"
        "نص قانوني متكامل للمادة الأولى.\n"
        "المادة 2\n"
        "نص قانوني متكامل للمادة الثانية.\n"
    )
    pages = [Page(number=1, text=content)]
    chunks = chunk_document("doc_triv", pages)

    assert len(chunks) == 2
    assert chunks[0].article == "المادة 1"
    assert "{" in chunks[0].text
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 2
    assert chunks[1].article == "المادة 2"
    assert chunks[1].chunk_index == 1
    assert chunks[1].total_chunks == 2

    # Isolated trivial chunk produces 0 chunks
    empty_pages = [Page(number=1, text="{\n   -  \n}")]
    empty_chunks = chunk_document("doc_empty", empty_pages)
    assert len(empty_chunks) == 0


def test_multi_text_two_decrees_segmentation() -> None:
    """Multi-text segmentation: two decrees of two articles each are cleanly partitioned.

    Article 2 of Decree 1 does not leak into Decree 2's title/visas, and Decree 2's chunks
    inherit Decree 2's title as the first element of hierarchy.
    """
    decree1_title = "مرسوم رقم 2.24.101 صادر في 15 يناير 2024"
    decree2_title = "مرسوم رقم 2.24.102 صادر في 20 فبراير 2024"

    content = (
        f"{decree1_title}\n"
        "بناء على الدستور،\n"
        "وعلى المرسوم رقم 2.20.10 المتعلق بالتنظيم،\n"
        "قرر ما يلي:\n"
        "المادة الأولى\n"
        "يحدد هذا المرسوم شروط ممارسة المهنة.\n"
        "المادة الثانية\n"
        "يسند تنفيذ هذا المرسوم إلى وزير العدل.\n"
        "وحرر بالرباط في 15 يناير 2024.\n"
        "الإمضاء: رئيس الحكومة.\n"
        f"{decree2_title}\n"
        "بناء على القانون رقم 70.03،\n"
        "قرر ما يلي:\n"
        "المادة الأولى\n"
        "تطبق أحكام هذا المرسوم على المؤسسات العامة.\n"
        "المادة الثانية\n"
        "ينشر هذا المرسوم بالجريدة الرسمية.\n"
        "وحرر بالرباط في 20 فبراير 2024.\n"
        "الإمضاء: رئيس الحكومة."
    )
    pages = [Page(number=1, text=content)]
    meta = DocumentMeta(title="مرسومان متتاليان", source_file="two_decrees.txt")

    chunks = chunk_document("multi_doc", pages, meta=meta)
    assert len(chunks) == 6

    # Decree 1 Preamble
    assert chunks[0].article is None
    assert chunks[0].hierarchy == [decree1_title]
    assert decree1_title in chunks[0].text

    # Decree 1 Article 1
    assert chunks[1].article == "المادة الأولى"
    assert chunks[1].hierarchy == [decree1_title]

    # Decree 1 Article 2: must contain signatures and NOT contain Decree 2 title
    assert chunks[2].article == "المادة الثانية"
    assert chunks[2].hierarchy == [decree1_title]
    assert "الإمضاء: رئيس الحكومة" in chunks[2].text
    assert decree2_title not in chunks[2].text
    assert "بناء على القانون رقم 70.03" not in chunks[2].text

    # Decree 2 Preamble: must contain Decree 2 title and visas
    assert chunks[3].article is None
    assert chunks[3].hierarchy == [decree2_title]
    assert decree2_title in chunks[3].text
    assert "بناء على القانون رقم 70.03" in chunks[3].text

    # Decree 2 Article 1: numbering resets to الأولى without error
    assert chunks[4].article == "المادة الأولى"
    assert chunks[4].hierarchy == [decree2_title]

    # Decree 2 Article 2
    assert chunks[5].article == "المادة الثانية"
    assert chunks[5].hierarchy == [decree2_title]


def test_visa_citation_does_not_split_text() -> None:
    """A decree cited inside visas ('وعلى المرسوم رقم...') does not trigger a text split."""
    content = (
        "مرسوم رقم 2.24.500 صادر في 10 مارس 2024\n"
        "بناء على الدستور،\n"
        "وعلى المرسوم رقم 2.18.100 الصادر بتنظيم القطاع،\n"
        "وعلى القرار رقم 1234.20 الصادر بتحديد المعايير،\n"
        "قرر ما يلي:\n"
        "المادة 1\n"
        "نص المادة الأولى.\n"
        "المادة 2\n"
        "نص المادة الثانية.\n"
        "وحرر بالرباط في 10 مارس 2024.\n"
        "الإمضاء: رئيس الحكومة."
    )
    pages = [Page(number=1, text=content)]
    meta = DocumentMeta(title="مرسوم وحيد", source_file="single_decree.txt")
    chunks = chunk_document("single_doc", pages, meta=meta)

    # 1 preamble + 2 articles = exactly 3 chunks (no extra text split)
    assert len(chunks) == 3
    assert chunks[0].article is None
    assert chunks[1].article == "المادة 1"
    assert chunks[2].article == "المادة 2"


def test_split_long_preferring_punctuation() -> None:
    """split_long prefers splitting at line ending with terminal punctuation (. ؛ : ؟)."""
    # Unit exceeding max_chunk_chars=120
    lines_with_punct = [
        (1, "المادة 1"),
        (1, "هذه الفقرة الأولى وتتضمن تفاصيل قانونية هامة وتوضيحات."),
        (1, "وهذه بداية الفقرة الثانية المستمرة في سرد الأحكام التنظيمية"),
        (1, "والتي تستكمل البيان بصورة وافية ومطولة."),
    ]
    u1 = _ChunkUnit(article="المادة 1", hierarchy=["الباب 1"], lines=lines_with_punct)
    # Total length is ~195 chars -> will split with max_chunk_chars=110
    splits = split_long([u1], max_chunk_chars=110)
    assert len(splits) == 2
    # Sub-chunk 0 should end with the line ending with '.'
    assert splits[0].lines[-1][1].endswith(".")
    assert "والفقرة الأولى" in splits[0].text or "هذه الفقرة الأولى" in splits[0].text

    # Unit without punctuation splits cleanly at line boundary
    lines_no_punct = [
        (1, "المادة 2"),
        (1, "سطر أول في المادة بدون أي علامات ترقيم"),
        (1, "سطر ثان يتابع الكلام القانوني"),
        (1, "سطر ثالث يتابع الكلام القانوني"),
    ]
    u2 = _ChunkUnit(article="المادة 2", hierarchy=["الباب 1"], lines=lines_no_punct)
    splits_no_punct = split_long([u2], max_chunk_chars=60)
    assert len(splits_no_punct) > 1
    # Check that all text is preserved
    full_recombined = "\n".join(s.text for s in splits_no_punct)
    for _, line_val in lines_no_punct:
        assert line_val in full_recombined


def test_sgg_7435_invariants_and_text_boundaries() -> None:
    """sgg_7435.pdf (read-only): no internal article/title headings; hierarchy non-empty."""
    p = Path("data/raw/public/sgg_7435.pdf")
    if not p.is_file():
        return

    fake_ocr = FakeOCRClient()
    pages = extract(p, ocr_client=fake_ocr)
    meta = DocumentMeta(title="الجريدة الرسمية عدد 7435", source_file=p.name)
    chunks = chunk_document("sgg_7435", pages, meta=meta)

    assert len(chunks) > 0

    # 1. No body chunk contains an article heading line after line 1
    for idx, c in enumerate(chunks):
        lines = c.text.splitlines()
        for line_idx in range(1, len(lines)):
            line_str = lines[line_idx].strip()
            assert not re.match(
                r"^(المادة|الفصل)\s+([0-9٠-٩]+|الأولى|الثانية)", line_str
            ), f"Chunk {idx} line {line_idx} contains unexpected article heading: {line_str}"
            # 2. No body chunk (p >= 4) contains a text title line after line 1
            if c.page_start >= 4:
                assert not _is_text_start_line(
                    line_str
                ), f"Chunk {idx} line {line_idx} contains unexpected text title: {line_str}"

        # 3. Hierarchy non-empty for BO chunks except the issue preamble (p < 4)
        if c.page_start >= 4:
            assert len(c.hierarchy) >= 1, f"Chunk {idx} on page {c.page_start} has empty hierarchy"
