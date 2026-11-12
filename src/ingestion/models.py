"""Data models internal to P1 (Ingestion).

Includes Page representation used during the extraction and cleaning stages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    """A single page extracted from a document (P1 internal).

    Attributes:
        number: 1-based page number within the document.
        text: Extracted, cleaned text of the page.
        ocr: True if this page was produced or recovered via OCR.
        confidence: Confidence score from OCRClient (0.0 to 1.0), or None if native text.
    """

    number: int
    text: str
    ocr: bool = False
    confidence: float | None = None

    @property
    def page(self) -> int:
        """Alias for number matching P1-13 cache serialization format."""
        return self.number
