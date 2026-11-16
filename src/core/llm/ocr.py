"""``HttpOCRClient``: the real ``OCRClient``, backed by the ``ocr`` service (P6-10, P6-12; §4.3).

The service runs Tesseract, which names languages with three letters (``ara``); the contract uses
two (``ar``). The client translates, and passes any other name through unchanged (``ara+fra``).

A page image can hold private text, so nothing about it is logged: only the error type or status.
"""

import logging

import httpx

from src.core.contracts.errors import ServiceError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120.0  # Tesseract can take tens of seconds on a dense scanned page
# Only the language packs installed in services/ocr/Dockerfile (tesseract-ocr-ara, -fra).
TESSERACT_LANGS = {"ar": "ara", "fr": "fra"}


class HttpOCRClient:
    """``OCRClient`` that sends one page image to the ``ocr`` service.

    Args:
        base_url: The ``ocr`` service (``ocr.base_url``).
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

    def ocr_page(self, image: bytes, lang: str = "ar") -> tuple[str, float]:
        """Returns the page's text and the engine's confidence, between 0 and 1.

        Args:
            image: An encoded PNG or JPEG file.
            lang: ``ar``, ``fr``, or a Tesseract language name installed in the service.

        Raises:
            ServiceError: The service is unreachable, refused the image, or gave a bad answer.
        """
        files = {"image": ("page.png", image, "application/octet-stream")}
        data = {"lang": TESSERACT_LANGS.get(lang, lang)}
        try:
            response = self.client.post("/ocr", files=files, data=data)
        except httpx.HTTPError as exc:
            logger.error("ocr unreachable", extra={"error": type(exc).__name__})
            raise ServiceError("ocr service unavailable") from exc
        if response.is_error:
            logger.error("ocr refused", extra={"status": response.status_code})
            raise ServiceError(f"ocr service refused the page ({response.status_code})")
        try:
            body = response.json()
            text, confidence = body["text"], float(body["confidence"])
        except (ValueError, KeyError, TypeError) as exc:
            logger.error("ocr bad answer", extra={"error": type(exc).__name__})
            raise ServiceError("ocr service gave an invalid answer") from exc
        if not isinstance(text, str):
            raise ServiceError("ocr service gave an invalid answer")
        return text, min(1.0, max(0.0, confidence))
