"""Unit tests for ``HttpLeakIndex``, against a mock ``web-search`` (P6-28, P6-31; T15)."""

import json
import re

import httpx
import pytest

from src.core.contracts.errors import ServiceError
from src.core.leak import real_leak_index
from src.core.leak.fingerprint import fingerprints
from src.core.leak.index import HttpLeakIndex

KEY = b"test-leak-key"
TOKEN = "test-token"
TEXT = "تلتزم الوكالة الوطنية بحماية المعطيات الشخصية وفق الدورية رقم 12/2025"
ARABIC = re.compile(r"[؀-ۿ]")


class Recorder:
    """A mock ``web-search``: records every request and answers with ``status``."""

    def __init__(self, status: int = 204) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


def _index(handler: Recorder | object) -> HttpLeakIndex:
    client = httpx.Client(base_url="http://web-search:8090", transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return HttpLeakIndex("http://web-search:8090", TOKEN, KEY, client=client)


def test_register_sends_only_fingerprints() -> None:
    """T15: /index receives the doc_id and hex fingerprints, never Arabic text."""
    web = Recorder()
    _index(web).register("doc-1", TEXT)
    [request] = web.requests
    assert (request.method, request.url.path) == ("POST", "/index")
    body = json.loads(request.content)
    grams, refs = fingerprints(TEXT, KEY)
    assert body == {"doc_id": "doc-1", "grams": grams, "refs": refs}
    assert not ARABIC.search(request.content.decode("utf-8"))


def test_set_blocking_sends_the_flag() -> None:
    web = Recorder()
    _index(web).set_blocking("doc-1", False)
    [request] = web.requests
    assert (request.method, request.url.path) == ("POST", "/blocking")
    assert json.loads(request.content) == {"doc_id": "doc-1", "blocking": False}


def test_delete_calls_the_document_path() -> None:
    web = Recorder()
    _index(web).delete("doc/1")
    [request] = web.requests
    assert request.method == "DELETE"
    assert request.url.raw_path == b"/index/doc%2F1"  # the doc_id cannot change the path


def test_every_call_carries_the_token() -> None:
    """P6-28."""
    web = Recorder()
    index = _index(web)
    index.register("doc-1", TEXT)
    index.set_blocking("doc-1", True)
    index.delete("doc-1")
    assert {r.headers["Authorization"] for r in web.requests} == {f"Bearer {TOKEN}"}


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_an_error_answer_is_a_service_error(status: int) -> None:
    """P6 spec §7: P1 then marks the document failed, P5's publication fails."""
    with pytest.raises(ServiceError):
        _index(Recorder(status)).register("doc-1", TEXT)


def test_an_unreachable_service_is_a_service_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ServiceError):
        _index(down).delete("doc-1")


def test_an_empty_token_is_refused() -> None:
    with pytest.raises(ServiceError):
        HttpLeakIndex("http://web-search:8090", "", KEY)


@pytest.mark.parametrize("missing", ["LEAK_API_TOKEN", "LEAK_HMAC_KEY"])
def test_real_leak_index_needs_the_token_and_the_key(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setenv("LEAK_API_TOKEN", TOKEN)
    monkeypatch.setenv("LEAK_HMAC_KEY", "key")
    monkeypatch.delenv(missing)
    with pytest.raises(ServiceError):
        real_leak_index()
