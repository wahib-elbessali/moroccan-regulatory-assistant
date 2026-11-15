"""Version file of the retrieval indexes (P2 spec P2-10, §6.5, §7).

BM25 lives in memory inside the ``api`` process, but Qdrant is also written by other code paths
(P1's command line). After every write to Qdrant, ``QdrantStore`` calls ``on_write``, which is
``bump_version``: the file gets a new random value. Before every search, ``BM25Index`` reads it
with ``read_version`` and rebuilds itself from Qdrant when the value has changed.

The file lives on the ``indexes`` volume of ``api`` (P6-01c) and is never committed. Its content
means nothing by itself; only "different from last time" matters.
"""

import contextlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from src.core.contracts import ServiceError

VERSION_FILE = Path("data/indexes/retrieval.version")


def bump_version(path: Path = VERSION_FILE) -> None:
    """Writes a new random value (``uuid4().hex``) to the version file, atomically.

    The value goes to a temporary file in the same directory, which then replaces the old file
    in one step, so a reader never sees a half-written value. The directory is created if
    missing. Callable with no argument, as ``QdrantStore``'s ``on_write``.

    Args:
        path: The version file. Tests pass a temporary path.

    Raises:
        ServiceError: The file could not be written. ``QdrantStore`` calls ``on_write`` outside
            its own error handling, so a raw ``OSError`` would otherwise reach the API as a 500.
    """
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=".retrieval-version-", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(uuid4().hex)
        os.replace(tmp, path)
    except OSError as exc:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        raise ServiceError("index version could not be written") from exc


def read_version(path: Path = VERSION_FILE) -> str | None:
    """The current value of the version file.

    Args:
        path: The version file. Tests pass a temporary path.

    Returns:
        The value, or ``None`` if the file is missing or empty: both mean "new version", so BM25
        is rebuilt (P2 spec §7).

    Raises:
        ServiceError: The file exists but could not be read.
    """
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ServiceError("index version could not be read") from exc
    return value or None
