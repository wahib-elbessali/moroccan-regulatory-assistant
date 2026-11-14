
"""Persistent SQLite storage for web-search leak fingerprints."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class SQLiteLeakStore:
    """File-backed index mapping HMAC fingerprints to document blocking states."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()


    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, manage its transaction and always close it."""
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()



    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    blocking INTEGER NOT NULL DEFAULT 1
                        CHECK (blocking IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS fingerprints (
                    doc_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('gram', 'ref')),
                    PRIMARY KEY (doc_id, fingerprint, kind),
                    FOREIGN KEY (doc_id)
                        REFERENCES documents(doc_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_fingerprints_lookup
                    ON fingerprints(fingerprint);
                """
            )

    def register(
        self,
        doc_id: str,
        grams: list[str],
        refs: list[str],
    ) -> None:
        """Replace a document's fingerprints and set it to blocking."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (doc_id, blocking)
                VALUES (?, 1)
                ON CONFLICT(doc_id) DO UPDATE SET blocking = 1
                """,
                (doc_id,),
            )
            connection.execute(
                "DELETE FROM fingerprints WHERE doc_id = ?",
                (doc_id,),
            )
            connection.executemany(
                """
                INSERT INTO fingerprints (doc_id, fingerprint, kind)
                VALUES (?, ?, 'gram')
                """,
                [(doc_id, fp) for fp in set(grams)],
            )
            connection.executemany(
                """
                INSERT INTO fingerprints (doc_id, fingerprint, kind)
                VALUES (?, ?, 'ref')
                """,
                [(doc_id, fp) for fp in set(refs)],
            )

    def set_blocking(self, doc_id: str, blocking: bool) -> None:
        """Change the blocking state; unknown documents are ignored."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE documents SET blocking = ? WHERE doc_id = ?",
                (int(blocking), doc_id),
            )

    def delete(self, doc_id: str) -> None:
        """Delete a document and its fingerprints; safe to call repeatedly."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM documents WHERE doc_id = ?",
                (doc_id,),
            )

    def get(self, fingerprint: str) -> list[tuple[str, bool, str]]:
        """Return (doc_id, blocking, kind) entries for a fingerprint."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.doc_id, d.blocking, f.kind
                FROM fingerprints AS f
                JOIN documents AS d ON d.doc_id = f.doc_id
                WHERE f.fingerprint = ?
                """,
                (fingerprint,),
            ).fetchall()

        return [(doc_id, bool(blocking), kind) for doc_id, blocking, kind in rows]
