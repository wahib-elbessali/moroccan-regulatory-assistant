"""Acceptance tests for IngestionPipeline (§6.1, §6.4, §7, T10-T18, T20, T22, T24)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src.core.contracts.enums import AuditAction, DocStatus
from src.core.contracts.fakes.retrieval import FakeRetrieval
from src.core.contracts.ids import make_doc_id
from src.core.contracts.models import DocumentMeta
from src.ingestion.pipeline import IngestionPipeline
from tests.ingestion.doubles import (
    LECTEUR_ID,
    OTHER_LECTEUR_ID,
    RecordingAudit,
    RecordingDocumentRights,
    RecordingLeakIndex,
    RecordingRetrieval,
    ScriptedOCRClient,
)


def _create_sample_pdf(path: Path, pages_text: list[str]) -> None:
    """Create a test PDF with given pages of text."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
    doc.save(str(path))
    doc.close()


def _create_sample_image(path: Path) -> None:
    """Create a sample 100x100 white image."""
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    img.save(str(path))


def test_t10_scanned_pdf_lifecycle(tmp_path: Path) -> None:
    """T10: Scanned PDF lifecycle extracting -> chunked -> indexed -> set_document_roles."""
    pdf_path = tmp_path / "scanned.pdf"
    _create_sample_pdf(pdf_path, [""])  # Empty page triggers OCR

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة 1\nيسري هذا القانون على كافة المعاملات.")
    cache_dir = tmp_path / "cache"

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=cache_dir,
    )

    doc_id = make_doc_id(b"scanned-doc-data", None)
    meta = DocumentMeta(title="قانون تجريبي", source_file="scanned.pdf")
    roles = ["lecteur", "editeur"]

    pipeline.ingest(doc_id, pdf_path, meta, roles, None)

    # Status sequence
    transitions = [s for _, s, _ in rights.status_history]
    assert transitions == [DocStatus.EXTRACTING, DocStatus.CHUNKED, DocStatus.INDEXED]
    assert rights.roles_set == [(doc_id, ["lecteur", "editeur"])]
    assert ocr.call_count == 1
    assert len(retrieval.indexed_chunks) >= 1
    assert len(leak.registered) == 1
    assert len(audit.actions) == 0


def test_t10b_jpg_photo_ocr(tmp_path: Path) -> None:
    """T10b: JPG photo calls OCR once, skips quality check, sets page_start=1."""
    jpg_path = tmp_path / "photo.jpg"
    _create_sample_image(jpg_path)

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة الأولى\nنص من صورة مستند قانوني.")
    cache_dir = tmp_path / "cache"

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=cache_dir,
    )

    doc_id = make_doc_id(b"jpg-photo-data", None)
    meta = DocumentMeta(title="صورة وثيقة", source_file="photo.jpg")

    pipeline.ingest(doc_id, jpg_path, meta, ["lecteur"], None)

    assert ocr.call_count == 1
    assert len(retrieval.indexed_chunks) == 1
    chunk = retrieval.indexed_chunks[0]
    assert chunk.page_start == 1
    assert chunk.page_end == 1
    assert chunk.article == "المادة الأولى"


def test_t11_retry_uses_cache(tmp_path: Path) -> None:
    """T11: Ingesting failed document again hits cache and does not call OCR."""
    pdf_path = tmp_path / "scanned.pdf"
    _create_sample_pdf(pdf_path, [""])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval(fail_index=RuntimeError("temporary index failure"))
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة 1\nنص المستند.")
    cache_dir = tmp_path / "cache"

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=cache_dir,
    )

    doc_id = make_doc_id(b"retry-doc-data", None)
    meta = DocumentMeta(title="وثيقة قابلة للإعادة", source_file="scanned.pdf")

    # First attempt: fails at index
    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)
    assert rights.get_status(doc_id) == DocStatus.FAILED
    assert ocr.call_count == 1
    assert (cache_dir / f"{doc_id}.json").exists()

    # Second attempt: retrieval fixed
    retrieval.fail_index = None
    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    # OCR was NOT called again (cache hit)
    assert ocr.call_count == 1
    assert rights.get_status(doc_id) == DocStatus.INDEXED
    assert len(retrieval.indexed_chunks) >= 1


def test_t12_chunks_allowed_roles_empty(tmp_path: Path) -> None:
    """T12: Chunks passed to retrieval.index always have allowed_roles == []."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nوثيقة ذات أدوار مقيدة."])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"doc-roles-empty", None)
    meta = DocumentMeta(title="وثيقة أدوار", source_file="doc.pdf")
    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur", "editeur"], None)

    assert len(retrieval.indexed_chunks) >= 1
    for chunk in retrieval.indexed_chunks:
        assert chunk.allowed_roles == []


def test_t13_private_upload_owner_id(tmp_path: Path) -> None:
    """T13: Private upload by user U sets owner_id == U on every chunk."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nوثيقة خاصة بالمستخدم."])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )

    user_u = LECTEUR_ID
    doc_id = make_doc_id(b"private-doc-data", user_u)
    meta = DocumentMeta(title="وثيقة خاصة", source_file="doc.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, [], user_u)

    assert len(retrieval.indexed_chunks) >= 1
    for chunk in retrieval.indexed_chunks:
        assert chunk.owner_id == user_u


def test_t14_too_many_scanned_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T14: Private upload with more scanned pages than quota fails with 'too many scanned pages'."""
    pdf_path = tmp_path / "multi_scanned.pdf"
    _create_sample_pdf(pdf_path, ["", "", ""])  # 3 empty pages

    # Quota set to 2 scanned pages
    monkeypatch.setattr(
        "src.ingestion.extract._read_config",
        lambda: {
            "ocr": {"max_pages_upload": 2},
            "ingestion": {"min_letters_per_page": 50, "ocr_min_confidence": 0.5},
        },
    )

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="نص", default_confidence=0.9)

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=tmp_path / "cache",
    )

    user_u = LECTEUR_ID
    doc_id = make_doc_id(b"too-many-pages-data", user_u)
    meta = DocumentMeta(title="وثيقة كبيرة", source_file="multi_scanned.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, [], user_u)

    assert rights.get_status(doc_id) == DocStatus.FAILED
    _, status, error = rights.status_history[-1]
    assert status == DocStatus.FAILED
    assert error == "too many scanned pages"
    assert ocr.call_count <= 2

    assert len(audit.actions) == 1
    assert audit.actions[0]["action_type"] == AuditAction.INGEST_FAILED
    assert audit.actions[0]["details"] == {
        "doc_id": doc_id,
        "reason": "too many scanned pages",
    }


def test_t15_retrieval_index_failure(tmp_path: Path) -> None:
    """T15: Index failure sets status failed, error 'RuntimeError', logs audit, does not set roles."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nنص تجريبي سري للغاية."])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval(fail_index=RuntimeError("connection refused to cluster"))
    leak = RecordingLeakIndex()
    audit = RecordingAudit()

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"index-fail-doc", None)
    meta = DocumentMeta(title="وثيقة فشل الفهرسة", source_file="doc.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    assert rights.get_status(doc_id) == DocStatus.FAILED
    _, status, error = rights.status_history[-1]
    assert status == DocStatus.FAILED
    assert error == "RuntimeError"  # Class name only, not "connection refused..."
    assert len(rights.roles_set) == 0

    assert len(audit.actions) == 1
    assert audit.actions[0]["action_type"] == AuditAction.INGEST_FAILED
    assert audit.actions[0]["details"] == {"doc_id": doc_id, "reason": "RuntimeError"}


def test_t16_delete_idempotent(tmp_path: Path) -> None:
    """T16: Deleting twice produces no error, calls P2 & P6 delete, and clears cache."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nوثيقة ستُحذف."])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    cache_dir = tmp_path / "cache"

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=cache_dir,
    )

    doc_id = make_doc_id(b"delete-doc-id", None)
    meta = DocumentMeta(title="وثيقة للحذف", source_file="doc.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)
    cache_file = cache_dir / f"{doc_id}.json"
    assert cache_file.exists()

    # First delete
    pipeline.delete(doc_id)
    assert retrieval.delete_calls == [doc_id]
    assert leak.delete_calls == [doc_id]
    assert not cache_file.exists()

    # Second delete (idempotent)
    pipeline.delete(doc_id)
    assert retrieval.delete_calls == [doc_id, doc_id]
    assert leak.delete_calls == [doc_id, doc_id]


def test_t17_cache_per_document(tmp_path: Path) -> None:
    """T17: Two users upload the same scanned file: cache is per document (doc_id)."""
    pdf_path = tmp_path / "shared_scan.pdf"
    _create_sample_pdf(pdf_path, [""])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة 1\nمحتوى ممسوح ضوئيا.")
    cache_dir = tmp_path / "cache"

    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=cache_dir,
    )

    user_a = LECTEUR_ID
    user_b = OTHER_LECTEUR_ID
    doc_id_a = make_doc_id(b"same-raw-data", user_a)
    doc_id_b = make_doc_id(b"same-raw-data", user_b)
    assert doc_id_a != doc_id_b

    meta_a = DocumentMeta(title="وثيقة أ", source_file="shared_scan.pdf")
    meta_b = DocumentMeta(title="وثيقة ب", source_file="shared_scan.pdf")

    pipeline.ingest(doc_id_a, pdf_path, meta_a, [], user_a)
    assert ocr.call_count == 1
    assert (cache_dir / f"{doc_id_a}.json").exists()

    pipeline.ingest(doc_id_b, pdf_path, meta_b, [], user_b)
    # OCR is called again because cache key is doc_id, not content
    assert ocr.call_count == 2
    assert (cache_dir / f"{doc_id_b}.json").exists()


def test_t18_no_document_text_in_failure_paths(tmp_path: Path) -> None:
    """T18: Sur CHAQUE chemin d'erreur, le message/statut ne contient AUCUN texte du document."""
    secret_text = "CONFIDENTIAL_SECRET_TOKEN_9999"

    # 1. Unsupported format
    txt_file = tmp_path / "file.unsupported"
    txt_file.write_text(f"المادة 1\n{secret_text}", encoding="utf-8")

    rights = RecordingDocumentRights()
    audit = RecordingAudit()
    pipeline = IngestionPipeline(rights=rights, audit=audit, cache_dir=tmp_path / "cache")
    doc_id = "doc-unsupported"
    pipeline.ingest(doc_id, txt_file, DocumentMeta(title="T", source_file="f.xyz"), [], None)
    assert rights.status_history[-1][2] == "unsupported format"
    assert secret_text not in str(rights.status_history)
    assert secret_text not in str(audit.actions)

    # 2. Cannot open file (corrupt PDF)
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(f"%PDF-invalid-{secret_text}".encode())
    pipeline.ingest(
        "doc-bad", bad_pdf, DocumentMeta(title="T", source_file="corrupt.pdf"), [], None
    )
    assert rights.status_history[-1][2] == "cannot open file"
    assert secret_text not in str(rights.status_history)
    assert secret_text not in str(audit.actions)

    # 3. No text extracted
    empty_pdf = tmp_path / "empty.pdf"
    _create_sample_pdf(empty_pdf, [""])
    ocr_empty = ScriptedOCRClient(default_text="")
    pipeline_empty = IngestionPipeline(
        rights=rights,
        audit=audit,
        ocr=ocr_empty,
        cache_dir=tmp_path / "cache",
    )
    pipeline_empty.ingest(
        "doc-empty", empty_pdf, DocumentMeta(title="T", source_file="empty.pdf"), [], None
    )
    assert rights.status_history[-1][2] == "no text extracted"
    assert secret_text not in str(rights.status_history)
    assert secret_text not in str(audit.actions)

    # 4. OCR quality too low
    low_conf_pdf = tmp_path / "low_conf.pdf"
    _create_sample_pdf(low_conf_pdf, ["", ""])
    ocr_low = ScriptedOCRClient(
        responses=[
            (f"نص صفحة 1 {secret_text}", 0.1),
            (f"نص صفحة 2 {secret_text}", 0.1),
        ]
    )
    pipeline_low = IngestionPipeline(
        rights=rights,
        audit=audit,
        ocr=ocr_low,
        cache_dir=tmp_path / "cache",
    )
    pipeline_low.ingest(
        "doc-low", low_conf_pdf, DocumentMeta(title="T", source_file="low_conf.pdf"), [], None
    )
    assert rights.status_history[-1][2] == "OCR quality too low"
    assert secret_text not in str(rights.status_history)
    assert secret_text not in str(audit.actions)

    # 5. Generic exception with secret in message
    valid_pdf = tmp_path / "valid.pdf"
    _create_sample_pdf(valid_pdf, [f"المادة 1\n{secret_text}"])
    retrieval_secret_err = RecordingRetrieval(
        fail_index=RuntimeError(f"crash containing {secret_text}")
    )
    pipeline_secret_err = IngestionPipeline(
        rights=rights,
        retrieval=retrieval_secret_err,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )
    pipeline_secret_err.ingest(
        "doc-err", valid_pdf, DocumentMeta(title="T", source_file="valid.pdf"), [], None
    )
    assert rights.status_history[-1][2] == "RuntimeError"
    assert secret_text not in str(rights.status_history)
    assert secret_text not in str(audit.actions)


def test_t20_document_meta_fields(tmp_path: Path) -> None:
    """T20: DocumentMeta fields (title, source_file, source) copied to every chunk."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["", ""])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(
        responses=[
            ("المادة 1\nالنص الأول للمادة الأولى.", 0.95),
            ("المادة 2\nالنص الثاني للمادة الثانية.", 0.95),
        ]
    )
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"meta-fields-doc", None)
    meta = DocumentMeta(
        title="مرسوم رقم 2.22.123",
        source_file="decree_22_123.pdf",
        source="https://sgg.gov.ma/decree.pdf",
    )

    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    assert len(retrieval.indexed_chunks) >= 2
    for chunk in retrieval.indexed_chunks:
        assert chunk.title == "مرسوم رقم 2.22.123"
        assert chunk.source_file == "decree_22_123.pdf"
        assert chunk.source == "https://sgg.gov.ma/decree.pdf"


def test_t22_reingest_drops_leftover_chunks(tmp_path: Path) -> None:
    """T22: Re-ingest with fewer chunks drops orphan chunks with index >= total_chunks."""
    # Test with FakeRetrieval to verify P2 contract drop behavior
    data_dir = tmp_path / "processed"
    fake_retrieval = FakeRetrieval(data_dir=data_dir)

    rights = RecordingDocumentRights()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    cache_dir = tmp_path / "cache"

    doc_id = make_doc_id(b"reingest-fewer-chunks", None)
    meta = DocumentMeta(title="وثيقة تحديث", source_file="doc.pdf")

    # First version: 5 articles -> 5 chunks
    v1_pdf = tmp_path / "v1.pdf"
    _create_sample_pdf(v1_pdf, [""] * 5)
    ocr_v1 = ScriptedOCRClient(
        responses=[(f"المادة {i}\nنص قانوني مفصل للمادة {i}.", 0.95) for i in range(1, 6)]
    )
    pipeline_v1 = IngestionPipeline(
        rights=rights,
        retrieval=fake_retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr_v1,
        cache_dir=cache_dir,
    )
    pipeline_v1.ingest(doc_id, v1_pdf, meta, ["lecteur"], None)
    records_v1 = [r for r in fake_retrieval._read() if r.get("doc_id") == doc_id]
    assert len(records_v1) == 5

    # Second version: 3 articles -> 3 chunks (clean cache to simulate modified content)
    cache_file = cache_dir / f"{doc_id}.json"
    cache_file.unlink()

    v2_pdf = tmp_path / "v2.pdf"
    _create_sample_pdf(v2_pdf, [""] * 3)
    ocr_v2 = ScriptedOCRClient(
        responses=[(f"المادة {i}\nنص معدل للمادة {i}.", 0.95) for i in range(1, 4)]
    )
    pipeline_v2 = IngestionPipeline(
        rights=rights,
        retrieval=fake_retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr_v2,
        cache_dir=cache_dir,
    )
    pipeline_v2.ingest(doc_id, v2_pdf, meta, ["lecteur"], None)
    records_v2 = [r for r in fake_retrieval._read() if r.get("doc_id") == doc_id]
    assert len(records_v2) == 3
    assert {r["chunk_index"] for r in records_v2} == {0, 1, 2}


def test_t24_document_date(tmp_path: Path) -> None:
    """T24: DocumentMeta date is copied to every chunk."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, [""])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة 1\nنص بتأريخ محدد.")
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"date-field-doc", None)
    meta = DocumentMeta(title="ظهير شريف", source_file="doc.pdf", date="2025-03-12")

    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    assert len(retrieval.indexed_chunks) >= 1
    for chunk in retrieval.indexed_chunks:
        assert chunk.date == "2025-03-12"


def test_leak_register_called_for_empty_roles(tmp_path: Path) -> None:
    """P1-29: Leak index registration must be performed for EVERY document, even with roles=[]."""
    pdf_path = tmp_path / "upload.pdf"
    _create_sample_pdf(pdf_path, [""])

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text="المادة 1\nنص مرفوع برواتب مقيدة أو خاصة.")
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        ocr=ocr,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"leak-empty-roles", LECTEUR_ID)
    meta = DocumentMeta(title="وثيقة خاصة", source_file="upload.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, [], LECTEUR_ID)

    assert len(leak.registered) == 1
    reg_doc_id, reg_text = leak.registered[0]
    assert reg_doc_id == doc_id
    assert "المادة 1" in reg_text


def test_set_document_roles_failure_warning_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """P1-30, §6.1: Failure in set_document_roles logs a warning without resetting status to failed."""
    pdf_path = tmp_path / "doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nنص سليم للاختبار."])

    rights = RecordingDocumentRights(fail_set_roles=RuntimeError("database row lock timeout"))
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"role-failure-doc", None)
    meta = DocumentMeta(title="وثيقة", source_file="doc.pdf")

    with caplog.at_level("WARNING"):
        pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    # Status remains indexed (NOT reset to failed)
    assert rights.get_status(doc_id) == DocStatus.INDEXED
    assert len(audit.actions) == 0  # No INGEST_FAILED logged

    # Warning logged
    assert any("publication failed" in record.message for record in caplog.records)


def test_retry_deletes_leftovers_before_extraction(tmp_path: Path) -> None:
    """P1-28: On retry (is_retry=True), retrieval.delete and leak.delete are called first."""
    pdf_path = tmp_path / "retry_doc.pdf"
    _create_sample_pdf(pdf_path, ["المادة 1\nنص الإعادة."])

    # Initial state: doc was failed
    rights = RecordingDocumentRights(initial_status=DocStatus.FAILED)
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    pipeline = IngestionPipeline(
        rights=rights,
        retrieval=retrieval,
        leak=leak,
        audit=audit,
        cache_dir=tmp_path / "cache",
    )

    doc_id = make_doc_id(b"retry-deletes-leftovers", None)
    meta = DocumentMeta(title="وثيقة إعادة", source_file="retry_doc.pdf")

    pipeline.ingest(doc_id, pdf_path, meta, ["lecteur"], None)

    assert doc_id in retrieval.delete_calls
    assert doc_id in leak.delete_calls
    assert rights.get_status(doc_id) == DocStatus.INDEXED
