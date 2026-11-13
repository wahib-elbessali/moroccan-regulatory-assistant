"""Tests for ingestion CLI and corpus seed tool (P1-33, T25)."""

from __future__ import annotations

import csv
from pathlib import Path

import pymupdf
import pytest

from src.core.contracts import registry
from src.core.contracts.enums import DocStatus
from src.core.contracts.errors import ServiceError
from src.core.contracts.ids import make_doc_id
from src.ingestion.cli import main
from tests.ingestion.doubles import (
    LECTEUR_ID,
    RecordingAudit,
    RecordingDocumentRights,
    RecordingIngestion,
    RecordingLeakIndex,
    RecordingRetrieval,
    ScriptedOCRClient,
)


def _setup_sample_file(path: Path, content: str = "محتوى اختباري للوثيقة.") -> Path:
    """Helper to write sample text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_t25_seed_twice_second_run_ignores_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T25: seed run twice on same manifest; second run ignores all existing documents."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    _setup_sample_file(raw_dir / "public" / "doc1.txt", "قانون رقم 1.")
    _setup_sample_file(raw_dir / "internal" / "doc2.txt", "مذكرة داخلية.")

    manifest_path = raw_dir / "manifest.csv"
    with open(manifest_path, "w", encoding="utf-8", newline="") as mf:
        writer = csv.DictWriter(
            mf,
            fieldnames=["file", "title", "visibility", "source_url", "date"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "file": "public/doc1.txt",
                "title": "قانون 1",
                "visibility": "public",
                "source_url": "https://sgg.gov.ma/1",
                "date": "2025-01-01",
            }
        )
        writer.writerow(
            {
                "file": "internal/doc2.txt",
                "title": "مذكرة 2",
                "visibility": "internal",
                "source_url": "",
                "date": "2025-02-01",
            }
        )

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    # First run
    code1 = main(["seed", "--raw-dir", str(raw_dir)], rights=rights, ingestion=ingestion)
    out1, _ = capsys.readouterr()

    assert code1 == 0
    assert "ingested=2 ignored=0 failed=0" in out1
    assert len(ingestion.ingest_calls) == 2

    # Second run (T25)
    code2 = main(["seed", "--raw-dir", str(raw_dir)], rights=rights, ingestion=ingestion)
    out2, _ = capsys.readouterr()

    assert code2 == 0
    assert "ingested=0 ignored=2 failed=0" in out2
    # Ingestion was not called again
    assert len(ingestion.ingest_calls) == 2


def test_seed_visibility_mapping(tmp_path: Path) -> None:
    """Visibility mappings: public -> ['lecteur', 'editeur'], internal -> ['editeur'], upload -> []."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    _setup_sample_file(raw_dir / "pub.txt", "نص عام")
    _setup_sample_file(raw_dir / "intern.txt", "نص داخلي")
    _setup_sample_file(raw_dir / "up.txt", "نص مستخدم")

    manifest_path = raw_dir / "manifest.csv"
    with open(manifest_path, "w", encoding="utf-8", newline="") as mf:
        writer = csv.DictWriter(
            mf, fieldnames=["file", "title", "visibility", "source_url", "date"]
        )
        writer.writeheader()
        writer.writerow({"file": "pub.txt", "title": "Pub", "visibility": "public"})
        writer.writerow({"file": "intern.txt", "title": "Intern", "visibility": "internal"})
        writer.writerow({"file": "up.txt", "title": "Up", "visibility": "upload"})

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    code = main(
        ["seed", "--raw-dir", str(raw_dir), "--owner", str(LECTEUR_ID)],
        rights=rights,
        ingestion=ingestion,
    )
    assert code == 0
    assert len(ingestion.ingest_calls) == 3

    calls_by_file = {call["meta"].source_file: call for call in ingestion.ingest_calls}
    assert calls_by_file["pub.txt"]["roles"] == ["lecteur", "editeur"]
    assert calls_by_file["pub.txt"]["owner_id"] is None

    assert calls_by_file["intern.txt"]["roles"] == ["editeur"]
    assert calls_by_file["intern.txt"]["owner_id"] is None

    assert calls_by_file["up.txt"]["roles"] == []
    assert calls_by_file["up.txt"]["owner_id"] == LECTEUR_ID


def test_seed_refused_without_owner_when_upload_rows_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pre-flight check: seed with upload rows and missing --owner returns exit code 2 immediately."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    _setup_sample_file(raw_dir / "up.txt")

    manifest_path = raw_dir / "manifest.csv"
    with open(manifest_path, "w", encoding="utf-8", newline="") as mf:
        writer = csv.DictWriter(mf, fieldnames=["file", "title", "visibility"])
        writer.writeheader()
        writer.writerow({"file": "up.txt", "title": "Upload Doc", "visibility": "upload"})

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    code = main(["seed", "--raw-dir", str(raw_dir)], rights=rights, ingestion=ingestion)
    _, err = capsys.readouterr()

    assert code == 2
    assert "Usage error: --owner is required" in err
    assert len(rights.created_docs) == 0
    assert len(ingestion.ingest_calls) == 0


def test_seed_missing_file_counts_as_failed_without_stopping_others(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing file row is counted as failed, remaining rows continue, exit code 1."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    _setup_sample_file(raw_dir / "present.txt")

    manifest_path = raw_dir / "manifest.csv"
    with open(manifest_path, "w", encoding="utf-8", newline="") as mf:
        writer = csv.DictWriter(mf, fieldnames=["file", "title", "visibility"])
        writer.writeheader()
        writer.writerow({"file": "missing.txt", "title": "Missing", "visibility": "public"})
        writer.writerow({"file": "present.txt", "title": "Present", "visibility": "public"})

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    code = main(["seed", "--raw-dir", str(raw_dir)], rights=rights, ingestion=ingestion)
    out, _ = capsys.readouterr()

    assert code == 1
    assert "ingested=1 ignored=0 failed=1" in out
    assert len(ingestion.ingest_calls) == 1
    assert ingestion.ingest_calls[0]["meta"].source_file == "present.txt"


def test_ingest_directory_ignores_hidden_and_unsupported(tmp_path: Path) -> None:
    """Ingesting a folder ignores dotfiles (.gitkeep) and unsupported extensions."""
    folder = tmp_path / "docs"
    folder.mkdir(parents=True, exist_ok=True)

    _setup_sample_file(folder / ".gitkeep", "")
    _setup_sample_file(folder / ".hidden.txt", "hidden")
    _setup_sample_file(folder / "ignored.bin", "binary")
    _setup_sample_file(folder / "valid1.txt", "نص سليم 1")
    _setup_sample_file(folder / "valid2.md", "نص سليم 2")

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    code = main(["ingest", str(folder), "--roles", "editeur"], rights=rights, ingestion=ingestion)
    assert code == 0
    assert len(ingestion.ingest_calls) == 2
    ingested_names = {call["meta"].source_file for call in ingestion.ingest_calls}
    assert ingested_names == {"valid1.txt", "valid2.md"}


def test_ingest_single_file_unsupported_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Explicitly ingesting an unsupported single file returns exit code 1."""
    bad_file = _setup_sample_file(tmp_path / "doc.unsupported", "unknown format")

    rights = RecordingDocumentRights()
    ingestion = RecordingIngestion(document_rights=rights)

    code = main(["ingest", str(bad_file)], rights=rights, ingestion=ingestion)
    out, _ = capsys.readouterr()

    assert code == 1
    assert "reason=unsupported format" in out
    assert len(ingestion.ingest_calls) == 0


def test_retry_failed_document_with_original_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Conflict with status failed triggers retry using the original file."""
    doc_path = _setup_sample_file(tmp_path / "retry.txt", "نص لإعادة المحاولة")
    data = doc_path.read_bytes()
    doc_id = make_doc_id(data, None)

    rights = RecordingDocumentRights()
    # Pre-register doc as failed
    rights.statuses[doc_id] = DocStatus.FAILED

    ingestion = RecordingIngestion(document_rights=rights)

    code = main(["ingest", str(doc_path), "--roles", "lecteur"], rights=rights, ingestion=ingestion)
    out, _ = capsys.readouterr()

    assert code == 0
    assert f"doc_id={doc_id} status=ingested" in out
    assert len(ingestion.ingest_calls) == 1
    assert ingestion.ingest_calls[0]["file_path"] == doc_path
    assert rights.get_status(doc_id) == DocStatus.READY


def test_no_document_text_in_any_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No CLI output stream (stdout or stderr) ever leaks document text or content."""
    secret_text = "CONFIDENTIAL_TOP_SECRET_CLI_PAYLOAD_999"
    doc_path = _setup_sample_file(tmp_path / "secret.txt", f"المادة 1\n{secret_text}")
    data = doc_path.read_bytes()
    doc_id = make_doc_id(data, None)

    rights = RecordingDocumentRights()
    # Simulate ingestion failure on this document
    ingestion = RecordingIngestion(document_rights=rights, fail_doc_ids={doc_id})

    code = main(["ingest", str(doc_path), "--roles", "lecteur"], rights=rights, ingestion=ingestion)
    out, err = capsys.readouterr()

    assert code == 1
    assert secret_text not in out
    assert secret_text not in err


def test_registry_unavailable_returns_code_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit code 3 if the registry fails to supply collaborators."""
    doc_path = _setup_sample_file(tmp_path / "doc.txt")

    def broken_get_document_rights() -> None:
        raise ServiceError("registry down")

    monkeypatch.setattr(
        "src.core.contracts.registry.get_document_rights",
        broken_get_document_rights,
    )

    code = main(["ingest", str(doc_path)])
    _, err = capsys.readouterr()

    assert code == 3
    assert "Registry error" in err


def test_cli_always_uses_real_pipeline_never_fake_ingestion(tmp_path: Path) -> None:
    """CLI must always use real_ingestion() with registry collaborators, never FakeIngestion."""
    # Create a small valid test PDF with unique content
    unique_marker = "UNIQUE_REAL_PIPELINE_MARKER_987654"
    pdf_path = tmp_path / "custom_doc.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 50, 500, 500),
        f"This is a digital document with more than fifty characters to verify real pipeline.\nMarker: {unique_marker}\n",
    )
    doc.save(str(pdf_path))
    doc.close()

    rights = RecordingDocumentRights()
    retrieval = RecordingRetrieval()
    leak = RecordingLeakIndex()
    audit = RecordingAudit()
    ocr = ScriptedOCRClient(default_text=f"ocr fallback {unique_marker}")

    registry.override("document_rights", rights)
    registry.override("retrieval", retrieval)
    registry.override("leak_index", leak)
    registry.override("audit", audit)
    registry.override("ocr", ocr)

    try:
        # Call main without passing ingestion collaborator: CLI must use real_ingestion()
        code = main(["ingest", str(pdf_path), "--roles", "editeur"])
        assert code == 0

        # Assert chunks come from THIS file, not sample_chunks.jsonl (which has 22 chunks)
        assert len(retrieval.indexed_chunks) >= 1
        assert len(retrieval.indexed_chunks) != 22  # FakeIngestion would index 22 chunks

        for chunk in retrieval.indexed_chunks:
            assert chunk.source_file == "custom_doc.pdf"
            assert chunk.title == "custom_doc"
            assert unique_marker in chunk.text
    finally:
        registry.reset()
