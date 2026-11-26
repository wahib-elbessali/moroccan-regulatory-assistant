"""Tests of the models service (services/models/app.py), with stub models: nothing is downloaded.

The module is loaded by path under its own name: web-search's tests also have an ``app`` module.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

APP_PATH = Path(__file__).resolve().parents[3] / "services" / "models" / "app.py"
_spec = importlib.util.spec_from_file_location("models_service_app", APP_PATH)
models_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(models_app)


class StubEmbedder:
    """Returns a 1024-float vector whose first value is the length of the text."""

    def __init__(self):
        self.calls = []

    def encode(self, texts, batch_size, normalize_embeddings):
        self.calls.append((list(texts), batch_size, normalize_embeddings))
        return [[float(len(t))] + [0.0] * 1023 for t in texts]


class StubReranker:
    """Scores a text by the number of words it shares with the query."""

    def __init__(self):
        self.calls = 0

    def predict(self, pairs):
        self.calls += 1
        return [float(len(set(q.split()) & set(t.split()))) for q, t in pairs]


@pytest.fixture
def client(monkeypatch):
    embedder, reranker = StubEmbedder(), StubReranker()
    monkeypatch.setattr(models_app, "load_models", lambda: (embedder, reranker))
    with TestClient(models_app.main) as test_client:
        test_client.embedder = embedder
        test_client.reranker = reranker
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_embed_returns_one_1024_vector_per_text_in_order(client):
    response = client.post("/embed", json={"texts": ["abc", "abcdef"]})
    assert response.status_code == 200
    vectors = response.json()["vectors"]
    assert [len(v) for v in vectors] == [1024, 1024]
    assert [v[0] for v in vectors] == [3.0, 6.0]


def test_embed_asks_for_normalized_vectors_in_batches(client):
    client.post("/embed", json={"texts": ["abc"]})
    texts, batch_size, normalize = client.embedder.calls[0]
    assert texts == ["abc"]
    assert batch_size == models_app.BATCH_SIZE
    assert normalize is True


def test_embed_empty_list_does_not_call_the_model(client):
    response = client.post("/embed", json={"texts": []})
    assert response.status_code == 200
    assert response.json() == {"vectors": []}
    assert client.embedder.calls == []


def test_embed_rejects_too_many_texts(client):
    response = client.post("/embed", json={"texts": ["x"] * (models_app.MAX_TEXTS + 1)})
    assert response.status_code == 422
    assert client.embedder.calls == []


def test_rerank_scores_follow_the_order_of_texts(client):
    body = {"query": "capital minimum SARL", "texts": ["recette du couscous", "capital minimum"]}
    response = client.post("/rerank", json=body)
    assert response.status_code == 200
    assert response.json() == {"scores": [0.0, 2.0]}


def test_rerank_empty_list_does_not_call_the_model(client):
    response = client.post("/rerank", json={"query": "q", "texts": []})
    assert response.status_code == 200
    assert response.json() == {"scores": []}
    assert client.reranker.calls == 0


def test_rerank_requires_a_query(client):
    response = client.post("/rerank", json={"texts": ["a"]})
    assert response.status_code == 422


class FakeModel:
    """Stands for a SentenceTransformer, or for the inner model of a CrossEncoder."""

    def __init__(self, name, device):
        self.name, self.device, self.half_precision = name, device, False

    def half(self):
        self.half_precision = True
        return self


class FakeCrossEncoder:
    def __init__(self, name, device):
        self.model = FakeModel(name, device)


@pytest.fixture
def fake_models(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"models": {"embedding": "org/embed", "reranker": "org/rerank"}}),
        encoding="utf-8",
    )
    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = FakeModel
    fake.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setattr(models_app, "CONFIG_PATH", config)


def test_load_models_uses_the_names_of_config_yaml(fake_models, monkeypatch):
    monkeypatch.setattr(models_app, "pick_device", lambda: "cpu")
    embedder, reranker = models_app.load_models()
    assert embedder.name == "org/embed"
    assert reranker.model.name == "org/rerank"


def test_load_models_on_the_processor_keeps_full_precision(fake_models, monkeypatch):
    monkeypatch.setattr(models_app, "pick_device", lambda: "cpu")
    embedder, reranker = models_app.load_models()
    assert (embedder.device, reranker.model.device) == ("cpu", "cpu")
    assert not embedder.half_precision and not reranker.model.half_precision


def test_load_models_on_the_card_uses_half_precision(fake_models, monkeypatch):
    monkeypatch.setattr(models_app, "pick_device", lambda: "cuda")
    embedder, reranker = models_app.load_models()
    assert (embedder.device, reranker.model.device) == ("cuda", "cuda")
    assert embedder.half_precision and reranker.model.half_precision


@pytest.mark.parametrize("available, device", [(True, "cuda"), (False, "cpu")])
def test_pick_device(available, device, monkeypatch):
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(is_available=lambda: available)
    monkeypatch.setitem(sys.modules, "torch", fake)
    assert models_app.pick_device() == device
