"""Tests for the persistent SQLite leak store."""

import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from store import SQLiteLeakStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteLeakStore:
    return SQLiteLeakStore(tmp_path / "leak.sqlite3")


def test_register_stores_grams_and_references(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["abc123", "def456"], ["ref123"])

    assert len(store.get("abc123")) == 1
    assert store.get("abc123")[0] == ("doc-1", True, "gram")
    assert store.get("ref123")[0] == ("doc-1", True, "ref")


def test_register_is_idempotent(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["abc123", "abc123"], [])
    store.register("doc-1", ["abc123"], [])

    assert store.get("abc123") == [("doc-1", True, "gram")]


def test_register_replaces_old_fingerprints(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["old123"], [])
    store.register("doc-1", ["new123"], [])

    assert store.get("old123") == []
    assert store.get("new123") == [("doc-1", True, "gram")]


def test_register_reactivates_blocking(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["abc123"], [])
    store.set_blocking("doc-1", False)

    assert store.get("abc123")[0][1] is False

    store.register("doc-1", ["abc123"], [])

    assert store.get("abc123")[0][1] is True


def test_set_blocking_is_idempotent(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["abc123"], [])

    store.set_blocking("doc-1", False)
    store.set_blocking("doc-1", False)

    assert store.get("abc123")[0][1] is False


def test_delete_removes_fingerprints(store: SQLiteLeakStore) -> None:
    store.register("doc-1", ["abc123"], ["ref123"])

    store.delete("doc-1")

    assert store.get("abc123") == []
    assert store.get("ref123") == []


def test_delete_is_idempotent(store: SQLiteLeakStore) -> None:
    store.delete("unknown-doc")
    store.delete("unknown-doc")


def test_unknown_document_can_be_updated_safely(
    store: SQLiteLeakStore,
) -> None:
    store.set_blocking("unknown-doc", True)
    assert store.get("unknown-fingerprint") == []


def test_data_survives_reopening_database(tmp_path: Path) -> None:
    db_path = tmp_path / "persistent.sqlite3"

    first = SQLiteLeakStore(db_path)
    first.register("doc-1", ["abc123"], [])

    second = SQLiteLeakStore(db_path)

    assert second.get("abc123") == [("doc-1", True, "gram")]
