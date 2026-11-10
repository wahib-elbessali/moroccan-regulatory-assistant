"""File-based fake of the ``Retrieval`` Protocol (00-shared §6.3, §9; P2 spec §3.2, §3.3, §3.5).

The real P2 keeps every chunk in Qdrant. This fake keeps them in one JSONL file,
``<fakes.data_dir>/chunks.jsonl``, so P1, P3 and P5 can build against the contract before Qdrant,
the embedding models and the config loader exist. One line per chunk: every field of the
``Chunk`` (00-shared §5.2) plus ``hidden``, exactly the payload the real store writes (P2-02).

``search`` ranks by simple word overlap (00-shared §9): no embeddings, no BM25, no RRF and no
re-ranker. The visibility rule is applied before scoring, so a chunk the user may not see is
never scored (P2-13).

Log lines and error messages never contain query text, chunk text or document titles (P2-29).
"""

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from src.ingestion.normalize import normalize_ar

from ..errors import AppError, InvalidInput, ServiceError
from ..ids import make_chunk_id
from ..models import Chunk, Passage, UserContext

logger = logging.getLogger(__name__)

CHUNKS_FILE = "chunks.jsonl"

# Defaults mirror config.yaml; the project has no config loader yet, so the caller passes the
# values it wants (tests point data_dir at a temporary folder).
DEFAULT_DATA_DIR = "data/processed"  # fakes.data_dir
DEFAULT_TOP_K_FINAL = 10  # retrieval.top_k_final
DEFAULT_RERANK_TOP_N = 20  # retrieval.rerank_top_n

# A stored record is the chunk's JSON fields plus "hidden"; "hidden" is kept out of the Chunk.
Record = dict[str, Any]


def _validate_chunks(chunks: list[Chunk]) -> None:
    """Checks a list of chunks before indexing (P2-05).

    The same rules as ``src/retrieval/store.py:validate_chunks``, repeated here so the fake stays
    free of ``qdrant_client``: the parts that only need the contract must be able to import it
    without the retrieval part or its dependencies.

    Raises:
        InvalidInput: Empty list, more than one ``doc_id``, different ``total_chunks`` values, a
            ``chunk_index`` outside ``0 … total_chunks - 1``, or a ``chunk_id`` that is not
            ``make_chunk_id(doc_id, chunk_index)``.
    """
    if not chunks:
        raise InvalidInput("no chunks to index")
    doc_id, total = chunks[0].doc_id, chunks[0].total_chunks
    for c in chunks:
        if c.doc_id != doc_id:
            raise InvalidInput("chunks from more than one document")
        if c.total_chunks != total:
            raise InvalidInput("total_chunks differs between chunks")
        if not 0 <= c.chunk_index < total:
            raise InvalidInput("chunk_index out of range")
        if c.chunk_id != make_chunk_id(doc_id, c.chunk_index):
            raise InvalidInput("chunk_id does not match doc_id and chunk_index")


@contextmanager
def _storage_errors(action: str) -> Iterator[None]:
    """Turns any file or JSON failure into ServiceError, with a message that holds no content."""
    try:
        yield
    except AppError:
        raise
    except Exception as exc:
        logger.error("chunk store failed", extra={"action": action, "error": type(exc).__name__})
        raise ServiceError(f"chunk store unavailable ({action})") from exc


def _match_text(chunk: Chunk) -> str:
    """The normalized text a query is matched against: the chunk text, its title and its article.

    The same fields the real BM25 index holds (P2-21). ``normalize_ar`` is idempotent (P1-17), so
    running it over ``text_normalized`` again is safe.
    """
    parts = (chunk.text_normalized, chunk.title, chunk.article or "")
    return " ".join(normalize_ar(part) for part in parts if part)


def _as_record(line: str) -> Record:
    """One JSONL line as a stored record.

    A line can be valid JSON without being a stored record: ``"hello"``, ``[]``, ``null`` and
    ``123`` all decode, but none of them has fields to read. Both failures raise here and the
    caller's ``_storage_errors`` turns them into the same ``ServiceError``.

    Raises:
        ValueError: The line is not valid JSON (``JSONDecodeError``) or is not a JSON object.
    """
    record = json.loads(line)
    if not isinstance(record, dict):
        raise ValueError("a stored line is not a JSON object")
    return record


def _index_of(record: Record) -> int:
    """``chunk_index`` of a stored record; a record without a usable one counts as a leftover."""
    value = record.get("chunk_index")
    return value if isinstance(value, int) else -1


def _to_chunk(record: Record) -> Chunk:
    """Rebuilds the ``Chunk`` from a stored record, leaving ``hidden`` out of the model.

    Raises:
        ServiceError: The record is not a valid chunk.
    """
    with _storage_errors("parse"):
        return Chunk.model_validate({k: v for k, v in record.items() if k != "hidden"})


def _visible(chunk: Chunk, ctx: UserContext) -> bool:
    """The visibility rule of 00-shared §6.3, without the ``hidden`` test (the caller does that).

    ``owner_id`` is stored as a JSON string; pydantic turns it back into a UUID when the record is
    validated, so the owner test compares UUID values and not their spellings.
    """
    owner: UUID | None = chunk.owner_id
    return owner == ctx.user_id or ctx.role in chunk.allowed_roles


class FakeRetrieval:
    """``Retrieval`` backed by ``<data_dir>/chunks.jsonl`` instead of Qdrant (00-shared §9).

    Args:
        data_dir: Where the JSONL file lives (``fakes.data_dir``). Tests pass ``tmp_path``.
        top_k_final: Default number of passages ``search`` returns (``retrieval.top_k_final``).
        rerank_top_n: The largest ``top_k`` ``search`` accepts (``retrieval.rerank_top_n``).

    Raises:
        ValueError: ``top_k_final`` below 1, or ``rerank_top_n`` below ``top_k_final``.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        top_k_final: int = DEFAULT_TOP_K_FINAL,
        rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    ) -> None:
        if top_k_final < 1:
            raise ValueError("top_k_final must be at least 1")
        if rerank_top_n < top_k_final:
            raise ValueError("rerank_top_n must be at least top_k_final")
        self.path = Path(data_dir) / CHUNKS_FILE
        self.top_k_final = top_k_final
        self.rerank_top_n = rerank_top_n

    # --- Indexing (§3.2) ----------------------------------------------------------------------

    def index(self, chunks: list[Chunk]) -> None:
        """Stores the chunks of one document, hidden (P2-05, P2-06, P2-09).

        A stored chunk with the same ``chunk_id`` is overwritten, any other chunk of that document
        with ``chunk_index >= total_chunks`` is dropped (left over from an older, longer version),
        and the chunks of every other document are kept untouched.

        Args:
            chunks: All chunks of one document, from P1, with ``allowed_roles`` as received.

        Raises:
            InvalidInput: The list is invalid (see ``_validate_chunks``); nothing is written.
            ServiceError: The JSONL file could not be read or written.
        """
        _validate_chunks(chunks)
        doc_id, total = chunks[0].doc_id, chunks[0].total_chunks
        with _storage_errors("serialize"):
            fresh = {c.chunk_id: {**c.model_dump(mode="json"), "hidden": True} for c in chunks}
        kept = [
            r
            for r in self._read()
            if r.get("doc_id") != doc_id
            or (r.get("chunk_id") not in fresh and _index_of(r) < total)
        ]
        self._write(kept + list(fresh.values()))
        logger.info("document indexed", extra={"doc_id": doc_id, "chunks": len(chunks)})

    # --- Search (§3.3) ------------------------------------------------------------------------

    def search(self, query: str, ctx: UserContext, top_k: int | None = None) -> list[Passage]:
        """Visible chunks that share a word with the query, best first (P2-11, P2-17).

        The visibility rule of 00-shared §6.3 is applied before scoring, so a hidden or restricted
        chunk is never scored or counted. ``score`` is the number of distinct query words the
        chunk's match text contains, not a re-ranker score. Equal scores are ordered by ``doc_id``
        then ``chunk_index``, so the same store always gives the same answer.

        Args:
            query: The question as typed.
            ctx: The user's context. Required.
            top_k: How many passages to return; ``None`` means ``top_k_final``.

        Returns:
            At most ``top_k`` passages, ``rank`` 1, 2, 3…, scores decreasing. ``[]`` when no
            visible chunk shares a word with the query.

        Raises:
            InvalidInput: ``ctx`` is None, the query is empty after ``normalize_ar``, or ``top_k``
                is outside ``1 … rerank_top_n`` (``top_k=0`` included: only ``None`` is a default).
            ServiceError: The JSONL file could not be read.
        """
        if ctx is None:
            raise InvalidInput("user context required")
        words = set(normalize_ar(query).split())
        if not words:
            raise InvalidInput("empty query")
        limit = self.top_k_final if top_k is None else top_k
        if not 1 <= limit <= self.rerank_top_n:
            raise InvalidInput("top_k out of range")

        scored: list[tuple[float, str, int, Chunk]] = []
        for record in self._read():
            if record.get("hidden", True):  # P2-13: a hidden chunk is never scored
                continue
            chunk = _to_chunk(record)
            if not _visible(chunk, ctx):
                continue
            score = float(len(words & set(_match_text(chunk).split())))
            if score:
                scored.append((score, chunk.doc_id, chunk.chunk_index, chunk))
        scored.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [
            Passage(chunk=chunk, score=score, rank=rank)
            for rank, (score, _, _, chunk) in enumerate(scored[:limit], start=1)
        ]

    # --- Rights and state (§3.5) --------------------------------------------------------------

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        """Sets ``allowed_roles`` on every chunk of the document; ``hidden`` is unchanged (P2-23).

        Idempotent; an unknown ``doc_id`` changes nothing and only logs a warning (P2-26).

        Raises:
            ServiceError: The JSONL file could not be read or written.
        """
        self._set_fields(doc_id, {"allowed_roles": list(roles)}, "update_roles")

    def hide(self, doc_id: str) -> None:
        """Sets ``hidden = True`` on every chunk of the document (P2-24). Idempotent.

        An unknown ``doc_id`` changes nothing and only logs a warning (P2-26).

        Raises:
            ServiceError: The JSONL file could not be read or written.
        """
        self._set_fields(doc_id, {"hidden": True}, "hide")

    def show(self, doc_id: str) -> None:
        """Sets ``hidden = False`` on every chunk of the document (P2-24). Idempotent.

        An unknown ``doc_id`` changes nothing and only logs a warning (P2-26).

        Raises:
            ServiceError: The JSONL file could not be read or written.
        """
        self._set_fields(doc_id, {"hidden": False}, "show")

    def delete(self, doc_id: str) -> None:
        """Deletes every chunk of the document (P2-25). Idempotent.

        An unknown ``doc_id`` changes nothing and only logs a warning (P2-26).

        Raises:
            ServiceError: The JSONL file could not be read or written.
        """
        records = self._read()
        kept = [r for r in records if r.get("doc_id") != doc_id]
        if len(kept) == len(records):
            logger.warning("no chunks for document", extra={"action": "delete", "doc_id": doc_id})
            return
        self._write(kept)

    def _set_fields(self, doc_id: str, fields: Record, action: str) -> None:
        """Writes ``fields`` into every record of the document, or warns if it has none."""
        records = self._read()
        touched = [r for r in records if r.get("doc_id") == doc_id]
        if not touched:
            logger.warning("no chunks for document", extra={"action": action, "doc_id": doc_id})
            return
        for record in touched:
            record.update(fields)
        self._write(records)

    # --- JSONL storage ------------------------------------------------------------------------

    def _read(self) -> list[Record]:
        """Every stored record, in file order. A missing file is an empty store.

        Raises:
            ServiceError: The file is unreadable, or holds a line that is not a JSON object
                (see ``_as_record``).
        """
        with _storage_errors("read"):
            if not self.path.exists():
                return []
            with self.path.open(encoding="utf-8") as handle:
                return [_as_record(line) for line in handle if line.strip()]

    def _write(self, records: list[Record]) -> None:
        """Replaces the file with ``records``, creating the parent directory if needed.

        The lines go to a temporary file in the same directory, which is then moved over the old
        one, so a failure half-way through leaves the previous contents in place.

        Raises:
            ServiceError: The directory or the file could not be written.
        """
        with _storage_errors("write"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    for record in records:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                os.replace(tmp, self.path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
