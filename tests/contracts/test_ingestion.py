"""Contract tests for the ``Ingestion`` Protocol (00-shared §6.2, §9; P1-ingestion §8).

Tests acceptance cases T10, T12, T13 and T16 of P1-ingestion.md §8, parametrized over both
implementations: ``FakeIngestion`` and the real one (marked skip until implemented).
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

# Ensure repository root is on sys.path
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.core.contracts import (  # noqa: E402
    Chunk,
    DocStatus,
    DocumentMeta,
    Ingestion,
    make_doc_id,
)
from src.core.contracts.fakes.ingestion import FakeIngestion  # noqa: E402
from tests.ingestion.doubles import (  # noqa: E402
    LECTEUR_ID,
    RecordingDocumentRights,
    RecordingLeakIndex,
    RecordingRetrieval,
)

REAL_FACTORY = "real_ingestion"


def _real_ingestion() -> Ingestion:
    """The real ingestion implementation, or a skip while it cannot be used."""
    try:
        module = importlib.import_module("src.ingestion")
    except ImportError as exc:
        pytest.skip(f"real ingestion dependencies unavailable ({type(exc).__name__})")
    factory: Callable[[], Ingestion] | None = getattr(module, REAL_FACTORY, None)
    if factory is None:
        pytest.skip(f"{REAL_FACTORY}() does not exist yet")
    try:
        return factory()
    except Exception as exc:
        pytest.skip(f"real ingestion unusable ({type(exc).__name__})")


class IngestionHarness:
    """Convenience test harness wrapping Ingestion and recording doubles."""

    def __init__(
        self,
        ingestion: Ingestion,
        retrieval: RecordingRetrieval,
        rights: RecordingDocumentRights,
        leak_index: RecordingLeakIndex,
        cache_dir: Path,
    ) -> None:
        self.ingestion = ingestion
        self.retrieval = retrieval
        self.rights = rights
        self.leak_index = leak_index
        self.cache_dir = cache_dir


@pytest.fixture(params=["fake", "real"])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> IngestionHarness:
    """Provides an Ingestion test harness for either the fake or real implementation."""
    cache_dir = tmp_path / "cache" / "extracted"
    cache_dir.mkdir(parents=True, exist_ok=True)

    retrieval = RecordingRetrieval()
    rights = RecordingDocumentRights()
    leak_index = RecordingLeakIndex()

    if request.param == "real":
        real = _real_ingestion()
        return IngestionHarness(real, retrieval, rights, leak_index, cache_dir)

    fake = FakeIngestion(
        retrieval=retrieval,
        document_rights=rights,
        leak_index=leak_index,
        extract_cache_dir=cache_dir,
    )
    return IngestionHarness(fake, retrieval, rights, leak_index, cache_dir)


# --- T10: Status progression and role handover (P1 spec §8) -----------------------------------


def test_t10_ingest_status_lifecycle_and_roles(harness: IngestionHarness, tmp_path: Path):
    """T10: Ingesting transitions extracting -> chunked -> indexed, then sets document roles."""
    doc_id = make_doc_id(b"test-scanned-pdf", None)
    dummy_file = tmp_path / "test_doc.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 test")

    meta = DocumentMeta(
        title="وثيقة اختبارية",
        source_file="test_doc.pdf",
        source="https://example.ma/doc",
        date="2026-11-11",
    )
    roles = ["lecteur", "editeur"]

    harness.ingestion.ingest(
        doc_id=doc_id,
        file_path=dummy_file,
        meta=meta,
        roles=roles,
        owner_id=None,
    )

    # Status sequence check
    transitions = [status for did, status, _ in harness.rights.status_history if did == doc_id]
    assert DocStatus.EXTRACTING in transitions
    assert DocStatus.CHUNKED in transitions
    assert DocStatus.INDEXED in transitions

    # Extracting must precede Chunked, Chunked must precede Indexed
    idx_ext = transitions.index(DocStatus.EXTRACTING)
    idx_chk = transitions.index(DocStatus.CHUNKED)
    idx_idx = transitions.index(DocStatus.INDEXED)
    assert idx_ext < idx_chk < idx_idx

    # Document rights set at the end with given roles
    assert (doc_id, roles) in harness.rights.roles_set


# --- T12: Chunks have allowed_roles == [] when passed to index (P1 spec §8) -------------------


def test_t12_chunks_have_empty_allowed_roles_when_indexed(
    harness: IngestionHarness, tmp_path: Path
):
    """T12: Any document ingested must pass chunks with allowed_roles == [] to retrieval.index."""
    doc_id = make_doc_id(b"test-public-doc", None)
    dummy_file = tmp_path / "public_doc.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 public")

    meta = DocumentMeta(title="وثيقة عامة", source_file="public_doc.pdf")
    roles = ["lecteur", "editeur"]

    harness.ingestion.ingest(
        doc_id=doc_id,
        file_path=dummy_file,
        meta=meta,
        roles=roles,
        owner_id=None,
    )

    assert len(harness.retrieval.indexed_chunks) > 0, "Chunks must have been indexed"
    for chunk in harness.retrieval.indexed_chunks:
        assert chunk.allowed_roles == [], (
            f"Chunk {chunk.chunk_id} must have allowed_roles == [] when indexed, "
            f"got {chunk.allowed_roles}"
        )


# --- T13: Private upload owner_id assigned to all chunks (P1 spec §8) -------------------------


def test_t13_private_upload_owner_id_assigned(harness: IngestionHarness, tmp_path: Path):
    """T13: A private upload by user U must result in every chunk having owner_id == U."""
    user_u = LECTEUR_ID
    doc_id = make_doc_id(b"test-private-upload", user_u)
    dummy_file = tmp_path / "private_upload.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 private")

    meta = DocumentMeta(title="وثيقة خاصة", source_file="private_upload.pdf")
    roles: list[str] = []

    harness.ingestion.ingest(
        doc_id=doc_id,
        file_path=dummy_file,
        meta=meta,
        roles=roles,
        owner_id=user_u,
    )

    assert len(harness.retrieval.indexed_chunks) > 0
    for chunk in harness.retrieval.indexed_chunks:
        assert chunk.owner_id == user_u, (
            f"Chunk {chunk.chunk_id} must have owner_id == {user_u}, got {chunk.owner_id}"
        )
        assert chunk.allowed_roles == []


# --- T16: Delete is idempotent and delegates to P2, P6 and cache (P1 spec §8) -----------------


def test_t16_delete_idempotent_and_cleans_up(harness: IngestionHarness, tmp_path: Path):
    """T16: Deleting a document twice raises no error, calls P2 & P6 delete, and clears cache."""
    doc_id = make_doc_id(b"test-to-delete", None)
    dummy_file = tmp_path / "delete_doc.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 to delete")

    # Seed an extraction cache file to verify cache cleanup (P1-32)
    cache_file = harness.cache_dir / f"{doc_id}.json"
    cache_file.write_text('{"pages": []}', encoding="utf-8")
    assert cache_file.exists()

    # Ingest document first
    meta = DocumentMeta(title="وثيقة للحذف", source_file="delete_doc.pdf")
    harness.ingestion.ingest(
        doc_id=doc_id,
        file_path=dummy_file,
        meta=meta,
        roles=["lecteur", "editeur"],
        owner_id=None,
    )

    # First delete call
    harness.ingestion.delete(doc_id)
    assert doc_id in harness.retrieval.delete_calls
    assert doc_id in harness.leak_index.delete_calls
    assert not cache_file.exists(), "Cache file must be deleted"

    # Second delete call (must not raise: idempotent)
    harness.ingestion.delete(doc_id)
    assert harness.retrieval.delete_calls.count(doc_id) == 2
    assert harness.leak_index.delete_calls.count(doc_id) == 2


# --- T15: Index failure sets status to failed without publishing (P1 spec §8) ------------------


def test_t15_index_failure_marks_document_failed(tmp_path: Path):
    """T15: When retrieval.index fails, status is set to failed and roles are not set."""
    retrieval = RecordingRetrieval(fail_index=RuntimeError("Qdrant connection timed out"))
    rights = RecordingDocumentRights()
    leak_index = RecordingLeakIndex()
    cache_dir = tmp_path / "cache" / "extracted"

    fake = FakeIngestion(
        retrieval=retrieval,
        document_rights=rights,
        leak_index=leak_index,
        extract_cache_dir=cache_dir,
    )

    doc_id = make_doc_id(b"test-failing-doc", None)
    dummy_file = tmp_path / "failing.pdf"
    dummy_file.write_bytes(b"%PDF-1.4 failing")

    meta = DocumentMeta(title="وثيقة فاشلة", source_file="failing.pdf")
    roles = ["lecteur", "editeur"]

    fake.ingest(
        doc_id=doc_id,
        file_path=dummy_file,
        meta=meta,
        roles=roles,
        owner_id=None,
    )

    # Status must be FAILED with a reason
    assert rights.get_status(doc_id) == DocStatus.FAILED
    failed_transitions = [
        err
        for did, status, err in rights.status_history
        if did == doc_id and status == DocStatus.FAILED
    ]
    assert len(failed_transitions) == 1
    assert failed_transitions[0] == "RuntimeError"

    # set_document_roles must not have been called
    assert len(rights.roles_set) == 0


# --- Visibility of root conftest fixture across test packages (00-shared §9) ------------------


def test_sample_chunks_fixture_visible_at_contracts_level(sample_chunks: list[Chunk]):
    """Verifies that the sample_chunks fixture in tests/conftest.py is visible to all parts."""
    assert isinstance(sample_chunks, list)
    assert len(sample_chunks) >= 20
    for chunk in sample_chunks:
        assert isinstance(chunk, Chunk)
