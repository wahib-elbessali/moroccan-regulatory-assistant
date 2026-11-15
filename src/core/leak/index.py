"""``HttpLeakIndex``: the real ``LeakIndex``, backed by the ``web-search`` service (P6-28, P6-31).

Fingerprints are computed here, inside ``api``; ``web-search`` only ever receives ``doc_id``s and
16-character hex strings (P6 spec §4.4, §7). Every call carries the shared token
``LEAK_API_TOKEN`` (P6-28).

If ``web-search`` cannot be reached or answers with an error, the call raises ``ServiceError``
(P6 spec §7): P1 then marks the document ``failed`` and P5's publication fails, so a document is
never shown while its fingerprints are missing.
"""

import logging
from urllib.parse import quote

import httpx

from src.core.contracts.errors import ServiceError

from .fingerprint import DEFAULT_NGRAM, fingerprints

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 5.0  # web.timeout_s


class HttpLeakIndex:
    """``LeakIndex`` that sends HMAC fingerprints to ``web-search`` over HTTP.

    Args:
        base_url: The ``web-search`` service (``web.base_url``).
        token: The shared token (``LEAK_API_TOKEN``).
        key: The shared HMAC key (``LEAK_HMAC_KEY``).
        ngram: Words per n-gram (``leak.ngram``).
        timeout_s: Seconds before a call gives up.
        client: An ``httpx.Client`` to use instead of a new one; tests pass one with a mock
            transport.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        key: bytes,
        *,
        ngram: int = DEFAULT_NGRAM,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ServiceError("LEAK_API_TOKEN is not set")
        self.key = key
        self.ngram = ngram
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self.headers = {"Authorization": f"Bearer {token}"}

    def register(self, doc_id: str, text: str) -> None:
        """Sends the document's fingerprints; ``web-search`` stores them blocking (P6-31).

        Raises:
            ServiceError: ``web-search`` is unreachable or refused the call.
        """
        grams, refs = fingerprints(text, self.key, self.ngram)
        self._call("POST", "/index", {"doc_id": doc_id, "grams": grams, "refs": refs})
        logger.info(
            "document fingerprints registered",
            extra={"doc_id": doc_id, "grams": len(grams), "refs": len(refs)},
        )

    def set_blocking(self, doc_id: str, blocking: bool) -> None:
        """Sets whether the document's fingerprints can block a query (P6-31).

        Raises:
            ServiceError: ``web-search`` is unreachable or refused the call.
        """
        self._call("POST", "/blocking", {"doc_id": doc_id, "blocking": blocking})

    def delete(self, doc_id: str) -> None:
        """Removes the document's fingerprints (P6-31). Idempotent on the ``web-search`` side.

        Raises:
            ServiceError: ``web-search`` is unreachable or refused the call.
        """
        self._call("DELETE", f"/index/{quote(doc_id, safe='')}", None)

    def _call(self, method: str, path: str, body: dict[str, object] | None) -> None:
        """One request to ``web-search``; any failure becomes a ``ServiceError`` with no content."""
        try:
            response = self.client.request(method, path, json=body, headers=self.headers)
        except httpx.HTTPError as exc:
            logger.error(
                "leak index unreachable", extra={"path": path, "error": type(exc).__name__}
            )
            raise ServiceError("leak index unavailable") from exc
        if response.is_error:
            logger.error("leak index refused", extra={"path": path, "status": response.status_code})
            raise ServiceError(f"leak index refused the call ({response.status_code})")
