"""Unit tests for ``HttpOCRClient``, against a mock ``ocr`` service (P6-10, P6-12; §4.3)."""

import httpx
import pytest

from src.core.contracts.errors import ServiceError
from src.core.llm.ocr import HttpOCRClient

PNG = b"\x89PNG\r\n\x1a\nfake-page"
TEXT = "هذا نص مستخرج من صفحة ممسوحة"


class Recorder:
    """A mock ``ocr`` service: records every request and answers with ``response``."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(200, json={"text": TEXT, "confidence": 0.87})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def _client(handler: object) -> HttpOCRClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return HttpOCRClient(
        "http://ocr:8070", client=httpx.Client(base_url="http://ocr:8070", transport=transport)
    )


def test_returns_the_text_and_the_confidence() -> None:
    assert _client(Recorder()).ocr_page(PNG) == (TEXT, 0.87)


def test_sends_the_image_as_multipart_to_ocr() -> None:
    ocr = Recorder()
    _client(ocr).ocr_page(PNG)
    [request] = ocr.requests
    assert (request.method, request.url.path) == ("POST", "/ocr")
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert PNG in request.content


@pytest.mark.parametrize(
    ("lang", "sent"), [("ar", b"ara"), ("fr", b"fra"), ("en", b"eng"), ("ara+fra", b"ara+fra")]
)
def test_translates_the_language_for_tesseract(lang: str, sent: bytes) -> None:
    ocr = Recorder()
    _client(ocr).ocr_page(PNG, lang)
    content = ocr.requests[0].content
    assert b'name="lang"\r\n\r\n' + sent + b"\r\n" in content


def test_default_language_is_arabic() -> None:
    ocr = Recorder()
    _client(ocr).ocr_page(PNG)
    assert b'name="lang"\r\n\r\nara\r\n' in ocr.requests[0].content


@pytest.mark.parametrize("confidence", [-0.5, 1.7])
def test_confidence_is_kept_between_0_and_1(confidence: float) -> None:
    ocr = Recorder(httpx.Response(200, json={"text": TEXT, "confidence": confidence}))
    _, got = _client(ocr).ocr_page(PNG)
    assert 0.0 <= got <= 1.0


@pytest.mark.parametrize("status", [400, 422, 500, 503])
def test_an_error_answer_is_a_service_error(status: int) -> None:
    with pytest.raises(ServiceError):
        _client(Recorder(httpx.Response(status))).ocr_page(PNG)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"text": TEXT}),
        httpx.Response(200, json={"text": None, "confidence": 0.5}),
        httpx.Response(200, json={"text": TEXT, "confidence": "high"}),
    ],
)
def test_an_invalid_answer_is_a_service_error(response: httpx.Response) -> None:
    with pytest.raises(ServiceError):
        _client(Recorder(response)).ocr_page(PNG)


def test_an_unreachable_service_is_a_service_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ServiceError):
        _client(down).ocr_page(PNG)
