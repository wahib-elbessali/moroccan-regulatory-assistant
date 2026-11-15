"""Document extraction engine for P1 (Ingestion) (P1-06 à P1-14, §6.2)."""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import UUID

import bs4
import docx
import pymupdf
import yaml
from PIL import Image, ImageEnhance, ImageSequence

from src.core.contracts.errors import InvalidInput
from src.core.contracts.protocols import OCRClient

from .arabic_pdf import extract_digital_pdf_pages, fix_inverted_headings
from .models import Page
from .ocr_clean import clean_ocr, remove_headers_footers
from .quality import passes_quality_check

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }
)


def sanitize_text(text: str) -> str:
    """Normalize via NFKC and strip Unicode Cc control characters (except \\n and \\t).

    Removes hidden control codes (e.g., \\x08 backspace found in Bulletin Officiel headers)
    while strictly preserving newlines, tabs, Arabic characters, and punctuation.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(c for c in normalized if c in ("\n", "\t") or unicodedata.category(c) != "Cc")


_sanitize_text = sanitize_text


def _read_config() -> dict[str, Any]:
    """Read root config.yaml located relative to module path without cwd dependency."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config.yaml"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _preprocess_image(img: Image.Image) -> bytes:
    """Preprocess image with Pillow: grayscale and contrast enhancement.

    Converts to PNG bytes for transmission to OCRClient.
    Note: Deskewing is omitted as it requires OpenCV/NumPy.
    """
    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(1.5)
    buf = io.BytesIO()
    enhanced.save(buf, format="PNG")
    return buf.getvalue()


def _resolve_ocr_client(ocr_client: OCRClient | None) -> OCRClient:
    """Resolve OCRClient from parameter or lazily from registry / FakeOCRClient."""
    if ocr_client is not None:
        return ocr_client
    try:
        from src.core.contracts.registry import get_ocr

        return get_ocr()
    except (ImportError, AttributeError):
        from src.core.contracts.fakes.llm import FakeOCRClient

        return FakeOCRClient()


def extract(
    file_path: Path | str,
    owner_id: UUID | None = None,
    ocr_client: OCRClient | None = None,
    min_letters_per_page: int | None = None,
    max_pages_upload: int | None = None,
    ocr_min_confidence: float | None = None,
) -> list[Page]:
    """Extract pages from any supported document format (P1-06 à P1-14, §6.2).

    Args:
        file_path: Path to the raw document file.
        owner_id: User UUID for private uploads (None for public corpus).
        ocr_client: OCR collaborator. If None, imported via get_ocr().
        min_letters_per_page: Digital text threshold (reads config if None).
        max_pages_upload: Max scanned pages allowed for upload (reads config if None).
        ocr_min_confidence: Min average confidence for OCR (reads config if None).

    Returns:
        List of extracted Page objects.

    Raises:
        InvalidInput("unsupported format"): If extension is not supported.
        InvalidInput("cannot open file"): If file is corrupted, encrypted, or unreadable.
        InvalidInput("too many scanned pages"): If private upload exceeds scan quota.
        InvalidInput("OCR quality too low"): If average OCR confidence is below threshold.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise InvalidInput("unsupported format")

    if min_letters_per_page is None or max_pages_upload is None or ocr_min_confidence is None:
        cfg = _read_config()
        if min_letters_per_page is None:
            min_letters_per_page = int(cfg["ingestion"]["min_letters_per_page"])
        if max_pages_upload is None:
            max_pages_upload = int(cfg["ocr"]["max_pages_upload"])
        if ocr_min_confidence is None:
            ocr_min_confidence = float(cfg["ingestion"]["ocr_min_confidence"])

    if suffix == ".pdf":
        return _extract_pdf(
            path,
            owner_id=owner_id,
            ocr_client=_resolve_ocr_client(ocr_client),
            min_letters_per_page=min_letters_per_page,
            max_pages_upload=max_pages_upload,
            ocr_min_confidence=ocr_min_confidence,
        )

    if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        return _extract_image(
            path,
            owner_id=owner_id,
            ocr_client=_resolve_ocr_client(ocr_client),
            max_pages_upload=max_pages_upload,
            ocr_min_confidence=ocr_min_confidence,
        )

    if suffix == ".docx":
        return _extract_docx(path)

    if suffix in (".html", ".htm"):
        return _extract_html(path)

    if suffix in (".md", ".markdown"):
        return _extract_markdown(path)

    if suffix == ".txt":
        return _extract_txt(path)

    raise InvalidInput("unsupported format")


def _extract_pdf(
    path: Path,
    owner_id: UUID | None,
    ocr_client: OCRClient,
    min_letters_per_page: int,
    max_pages_upload: int,
    ocr_min_confidence: float,
) -> list[Page]:
    """Extract pages from a PDF, falling back to OCR when quality check fails."""
    try:
        doc = pymupdf.open(str(path))
        if doc.is_encrypted:
            raise InvalidInput("cannot open file")
    except Exception as exc:
        if isinstance(exc, InvalidInput):
            raise
        raise InvalidInput("cannot open file") from None

    pages: list[Page] = []
    ocr_count = 0
    ocr_confidences: list[float] = []

    try:
        # Extract digital pages with conditional Arabic ligature repair (P1-07, §6.2)
        candidate_pages, _, _ = extract_digital_pdf_pages(doc)

        for page_index in range(len(doc)):
            n = page_index + 1
            page = doc[page_index]
            text = sanitize_text(candidate_pages[page_index])

            if passes_quality_check(text, min_letters=min_letters_per_page):
                pages.append(Page(number=n, text=text, ocr=False, confidence=None))
            else:
                ocr_count += 1
                if owner_id is not None and ocr_count > max_pages_upload:
                    raise InvalidInput("too many scanned pages")

                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                ocr_text, conf = ocr_client.ocr_page(img_bytes, "ar")
                ocr_confidences.append(conf)
                cleaned = fix_inverted_headings(clean_ocr(sanitize_text(ocr_text)))
                pages.append(Page(number=n, text=cleaned, ocr=True, confidence=conf))
    finally:
        doc.close()

    if ocr_confidences:
        avg_conf = sum(ocr_confidences) / len(ocr_confidences)
        if avg_conf < ocr_min_confidence:
            raise InvalidInput("OCR quality too low")

    return remove_headers_footers(pages)


def _extract_image(
    path: Path,
    owner_id: UUID | None,
    ocr_client: OCRClient,
    max_pages_upload: int,
    ocr_min_confidence: float,
) -> list[Page]:
    """Extract pages from images (PNG, JPG, TIFF) via direct OCR (P1-06b)."""
    try:
        img = Image.open(str(path))
        frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
    except Exception:
        raise InvalidInput("cannot open file") from None

    if owner_id is not None and len(frames) > max_pages_upload:
        raise InvalidInput("too many scanned pages")

    pages: list[Page] = []
    ocr_confidences: list[float] = []

    for n, frame in enumerate(frames, start=1):
        img_bytes = _preprocess_image(frame)
        text, conf = ocr_client.ocr_page(img_bytes, "ar")
        ocr_confidences.append(conf)
        cleaned = fix_inverted_headings(clean_ocr(sanitize_text(text)))
        pages.append(Page(number=n, text=cleaned, ocr=True, confidence=conf))

    if ocr_confidences:
        avg_conf = sum(ocr_confidences) / len(ocr_confidences)
        if avg_conf < ocr_min_confidence:
            raise InvalidInput("OCR quality too low")

    return pages


def _extract_docx(path: Path) -> list[Page]:
    """Extract paragraphs and tables from DOCX files."""
    try:
        doc = docx.Document(str(path))
    except Exception:
        raise InvalidInput("cannot open file") from None

    parts: list[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)

    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_cells:
                parts.append(" | ".join(row_cells))

    full_text = sanitize_text("\n".join(parts))
    return [Page(number=1, text=full_text, ocr=False, confidence=None)]


def _extract_html(path: Path) -> list[Page]:
    """Extract clean text from HTML, removing script, style, nav, and footer tags."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="cp1256")
        except Exception:
            raise InvalidInput("cannot open file") from None
    except Exception:
        raise InvalidInput("cannot open file") from None

    soup = bs4.BeautifulSoup(content, "html.parser")
    for elem in soup(["script", "style", "nav", "footer"]):
        elem.decompose()

    text = soup.get_text(separator="\n", strip=True)
    full_text = sanitize_text(text)
    return [Page(number=1, text=full_text, ocr=False, confidence=None)]


def _extract_markdown(path: Path) -> list[Page]:
    """Extract text from Markdown, stripping only line-starting heading hashes."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        raise InvalidInput("cannot open file") from None

    lines = [re.sub(r"^#{1,6}\s+", "", line) for line in content.splitlines()]
    full_text = sanitize_text("\n".join(lines).strip())
    return [Page(number=1, text=full_text, ocr=False, confidence=None)]


def _extract_txt(path: Path) -> list[Page]:
    """Extract text from TXT, reading utf-8-sig then falling back to cp1256."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="cp1256")
        except Exception:
            raise InvalidInput("cannot open file") from None
    except Exception:
        raise InvalidInput("cannot open file") from None

    full_text = sanitize_text(content.strip())
    return [Page(number=1, text=full_text, ocr=False, confidence=None)]
