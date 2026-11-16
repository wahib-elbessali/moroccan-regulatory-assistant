"""``HttpModelsClient``: the real ``ModelsClient``, backed by the ``models`` service (P6-09).

The service (``services/models``) serves bge-m3 embeddings and bge-reranker-v2-m3 scores over HTTP
(P6 spec §4.2). Long lists are sent in batches, and the answer is checked: a wrong number of
results or a wrong vector size would corrupt the index silently, so it raises instead.

If the service cannot be reached, answers with an error or sends an unreadable answer, the call
raises ``ServiceError`` (P6 spec §7). The texts are never logged: they come from documents that
may be confidential.
"""

import logging
from collections.abc import Iterator

import httpx

from src.core.contracts.errors import ServiceError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120.0  # both models run on the CPU: a batch can take a while
EMBEDDING_DIM = 1024  # bge-m3
MAX_TEXTS_PER_CALL = 64  # the service refuses more than 256 texts per request


def _batches(texts: list[str]) -> Iterator[list[str]]:
    for start in range(0, len(texts), MAX_TEXTS_PER_CALL):
        yield texts[start : start + MAX_TEXTS_PER_CALL]


class HttpModelsClient:
    """``ModelsClient`` that calls the ``models`` service over HTTP.

    Args:
        base_url: The ``models`` service (``models.base_url``).
        timeout_s: Seconds before a call gives up.
        client: An ``httpx.Client`` to use instead of a new one; tests pass one with a mock
            transport.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """bge-m3 vectors (1024 floats each), in the order of ``texts``.

        Raises:
            ServiceError: the service is unreachable, refused the call or sent a wrong answer.
        """
        vectors: list[list[float]] = []
        for batch in _batches(texts):
            vectors.extend(self._call("/embed", {"texts": batch}, "vectors", len(batch)))
        if any(not isinstance(v, list) or len(v) != EMBEDDING_DIM for v in vectors):
            raise ServiceError("models service sent vectors of the wrong size")
        return vectors

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Re-ranker scores, in the order of ``texts``; higher is better.

        Raises:
            ServiceError: the service is unreachable, refused the call or sent a wrong answer.
        """
        scores: list[float] = []
        for batch in _batches(texts):
            body = {"query": query, "texts": batch}
            scores.extend(self._call("/rerank", body, "scores", len(batch)))
        return [float(s) for s in scores]

    def _call(self, path: str, body: dict[str, object], key: str, expected: int) -> list:
        """One request to the service; any failure becomes a ``ServiceError`` with no content."""
        try:
            response = self.client.post(path, json=body)
        except httpx.HTTPError as exc:
            logger.error(
                "models service unreachable", extra={"path": path, "error": type(exc).__name__}
            )
            raise ServiceError("models service unavailable") from exc
        if response.is_error:
            logger.error(
                "models service refused", extra={"path": path, "status": response.status_code}
            )
            raise ServiceError(f"models service refused the call ({response.status_code})")
        try:
            values = response.json()[key]
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("models service sent an unreadable answer") from exc
        if not isinstance(values, list) or len(values) != expected:
            raise ServiceError("models service sent an answer of the wrong size")
        return values
