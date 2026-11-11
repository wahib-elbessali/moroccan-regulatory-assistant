"""Tests of src/retrieval/version.py (P2 spec P2-10, §6.5, §7)."""

import re
from pathlib import Path

import pytest
from p2_helpers import HashModels, make_doc
from qdrant_client import QdrantClient

from src.core.contracts import ServiceError
from src.retrieval import version as version_module
from src.retrieval.store import QdrantStore
from src.retrieval.version import VERSION_FILE, bump_version, read_version

UUID4_HEX = re.compile(r"[0-9a-f]{32}")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "indexes" / "retrieval.version"


# --- read_version ------------------------------------------------------------------------------


def test_missing_file_reads_none(path: Path) -> None:
    assert read_version(path) is None


def test_empty_file_reads_none(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    assert read_version(path) is None


def test_unreadable_file_raises_service_error(tmp_path: Path) -> None:
    with pytest.raises(ServiceError):
        read_version(tmp_path)  # a directory, not a file


# --- bump_version ------------------------------------------------------------------------------


def test_bump_creates_directory_and_file(path: Path) -> None:
    assert not path.parent.exists()
    bump_version(path)
    assert path.is_file()


def test_bumped_value_is_a_uuid4_hex(path: Path) -> None:
    bump_version(path)
    value = read_version(path)
    assert value is not None
    assert UUID4_HEX.fullmatch(value)


def test_read_returns_exactly_what_was_written(path: Path) -> None:
    bump_version(path)
    assert read_version(path) == path.read_text(encoding="utf-8")


def test_each_bump_gives_a_new_value(path: Path) -> None:
    values = set()
    for _ in range(5):
        bump_version(path)
        values.add(read_version(path))
    assert len(values) == 5


def test_no_temporary_file_left_behind(path: Path) -> None:
    bump_version(path)
    bump_version(path)
    assert list(path.parent.iterdir()) == [path]


def test_bump_without_argument_uses_version_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # VERSION_FILE is relative: it lands under tmp_path
    bump_version()
    assert read_version() is not None
    assert (tmp_path / VERSION_FILE).is_file()


def test_directory_that_cannot_be_created_raises_service_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")  # a file where the directory should be
    with pytest.raises(ServiceError) as excinfo:
        bump_version(blocker / "retrieval.version")
    assert "blocker" not in str(excinfo.value)  # no path or content in the message


def test_failed_replace_keeps_old_value_and_cleans_up(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bump_version(path)
    before = read_version(path)

    def fail(*_args: object) -> None:
        raise PermissionError("file in use")

    monkeypatch.setattr(version_module.os, "replace", fail)
    with pytest.raises(ServiceError):
        bump_version(path)
    assert read_version(path) == before
    assert list(path.parent.iterdir()) == [path]


# --- With QdrantStore, as its on_write ---------------------------------------------------------


def test_store_writes_bump_the_version(qdrant: QdrantClient, collection: str, path: Path) -> None:
    store = QdrantStore(
        qdrant, HashModels(), collection=collection, on_write=lambda: bump_version(path)
    )
    store.ensure_collection()
    chunks = make_doc("versioned")
    doc_id = chunks[0].doc_id

    store.index(chunks)
    after_index = read_version(path)
    assert after_index is not None

    store.hide(doc_id)
    after_hide = read_version(path)
    assert after_hide != after_index

    store.hide("unknown-doc")  # nothing written in Qdrant, so no bump (P2-26)
    assert read_version(path) == after_hide
