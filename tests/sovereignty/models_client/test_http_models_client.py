"""Tests of ``HttpModelsClient`` against a mock transport: no service, no model."""

from __future__ import annotations

import logging

import httpx
import pytest

from src.core.contracts.errors import ServiceError
from src.core.llm.models import EMBEDDING_DIM, MAX_TEXTS_PER_CALL, HttpModelsClient

BASE_URL = "http://models:8080"


def vector(first: float) -> list[float]:
    return [first] + [0.0] * (EMBEDDING_DIM - 1)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return HttpModelsClient(BASE_URL, client=httpx.Client(base_url=BASE_URL, transport=transport))


class FakeService:
    """Answers like the real service: a vector per text, a score per text."""

    def __init__(self):
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, content=request.content).json()
        self.requests.append((request.url.path, body))
        if request.url.path == "/embed":
            return httpx.Response(200, json={"vectors": [vector(len(t)) for t in body["texts"]]})
        scores = [float(len(set(body["query"].split()) & set(t.split()))) for t in body["texts"]]
        return httpx.Response(200, json={"scores": scores})


def test_embed_returns_the_vectors_in_the_order_of_the_texts():
    service = FakeService()
    vectors = make_client(service).embed(["abc", "abcdef"])
    assert [v[0] for v in vectors] == [3.0, 6.0]
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    assert service.requests == [("/embed", {"texts": ["abc", "abcdef"]})]


def test_embed_empty_list_makes_no_call():
    service = FakeService()
    assert make_client(service).embed([]) == []
    assert service.requests == []


def test_embed_sends_long_lists_in_batches_and_keeps_the_order():
    service = FakeService()
    texts = ["x" * (i + 1) for i in range(MAX_TEXTS_PER_CALL * 2 + 22)]
    vectors = make_client(service).embed(texts)
    assert [len(body["texts"]) for _, body in service.requests] == [
        MAX_TEXTS_PER_CALL,
        MAX_TEXTS_PER_CALL,
        22,
    ]
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]


def test_embed_rejects_vectors_of_the_wrong_size():
    def handler(request):
        return httpx.Response(200, json={"vectors": [[0.1, 0.2]]})

    with pytest.raises(ServiceError):
        make_client(handler).embed(["abc"])


def test_embed_rejects_a_wrong_number_of_vectors():
    def handler(request):
        return httpx.Response(200, json={"vectors": [vector(1.0)]})

    with pytest.raises(ServiceError):
        make_client(handler).embed(["a", "b"])


def test_rerank_returns_the_scores_in_the_order_of_the_texts():
    service = FakeService()
    scores = make_client(service).rerank("capital minimum", ["couscous", "capital minimum SARL"])
    assert scores == [0.0, 2.0]
    assert service.requests == [
        ("/rerank", {"query": "capital minimum", "texts": ["couscous", "capital minimum SARL"]})
    ]


def test_rerank_empty_list_makes_no_call():
    service = FakeService()
    assert make_client(service).rerank("q", []) == []
    assert service.requests == []


def test_rerank_sends_long_lists_in_batches_and_keeps_the_order():
    service = FakeService()
    texts = ["a"] * MAX_TEXTS_PER_CALL + ["b"]
    scores = make_client(service).rerank("b", texts)
    assert len(service.requests) == 2
    assert scores == [0.0] * MAX_TEXTS_PER_CALL + [1.0]


def test_rerank_rejects_a_wrong_number_of_scores():
    def handler(request):
        return httpx.Response(200, json={"scores": [0.5]})

    with pytest.raises(ServiceError):
        make_client(handler).rerank("q", ["a", "b"])


def test_unreachable_service_raises_service_error():
    def handler(request):
        raise httpx.ConnectError("no route")

    client = make_client(handler)
    with pytest.raises(ServiceError):
        client.embed(["abc"])
    with pytest.raises(ServiceError):
        client.rerank("q", ["abc"])


def test_error_status_raises_service_error_without_the_texts(caplog):
    def handler(request):
        return httpx.Response(500, json={"detail": "secret text"})

    with caplog.at_level(logging.ERROR), pytest.raises(ServiceError) as raised:
        make_client(handler).embed(["confidential paragraph"])
    assert "500" in str(raised.value)
    assert "confidential paragraph" not in caplog.text
    assert "confidential paragraph" not in str(raised.value)


def test_unreadable_answer_raises_service_error():
    def handler(request):
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(ServiceError):
        make_client(handler).embed(["abc"])


def test_answer_without_the_expected_key_raises_service_error():
    def handler(request):
        return httpx.Response(200, json={"unexpected": []})

    with pytest.raises(ServiceError):
        make_client(handler).rerank("q", ["abc"])


def test_real_models_builds_the_client_from_the_config():
    from src.core.llm import real_models

    client = real_models()
    assert isinstance(client, HttpModelsClient)
    assert str(client.client.base_url).startswith("http://models:8080")
