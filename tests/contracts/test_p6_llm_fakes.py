import pytest

from src.core.contracts.fakes.llm import (
    FakeLLMClient,
    FakeModelsClient,
    FakeOCRClient,
)


def test_fake_llm_returns_configured_replies():
    client = FakeLLMClient(replies=["First response", "Second response"])

    assert client.chat([]) == "First response"
    assert client.chat([]) == "Second response"


def test_fake_llm_uses_default_reply_when_queue_is_empty():
    client = FakeLLMClient(default_reply="Fallback")

    assert client.chat([]) == "Fallback"
    assert client.chat([]) == "Fallback"


@pytest.mark.asyncio
async def test_fake_llm_stream_reconstructs_response():
    client = FakeLLMClient(replies=["Hello Moroccan AI"])

    chunks = [chunk async for chunk in client.stream([])]

    assert "".join(chunks) == "Hello Moroccan AI"


def test_fake_llm_counts_words():
    client = FakeLLMClient()

    assert client.count_tokens("Moroccan Regulatory Assistant") == 3
    assert client.count_tokens("") == 0


def test_fake_ocr_returns_arabic_text_and_confidence():
    client = FakeOCRClient()

    text, confidence = client.ocr_page(b"fake-image")

    assert isinstance(text, str)
    assert "وثيقة" in text
    assert confidence == 0.9


def test_fake_models_embeddings_are_deterministic():
    client = FakeModelsClient()

    first = client.embed(["Moroccan law"])
    second = client.embed(["Moroccan law"])

    assert first == second


def test_fake_models_embedding_dimension():
    client = FakeModelsClient()

    embeddings = client.embed(["Text one", "Text two"])

    assert len(embeddings) == 2
    assert all(len(vector) == 1024 for vector in embeddings)


def test_fake_models_embeddings_are_normalized():
    client = FakeModelsClient()

    embeddings = client.embed(["Moroccan law"])

    norm = sum(value**2 for value in embeddings[0]) ** 0.5

    assert norm == pytest.approx(1.0)


def test_fake_models_reranking():
    client = FakeModelsClient()

    scores = client.rerank(
        "tax declaration",
        [
            "tax declaration deadline",
            "weather forecast",
            "tax payment",
        ],
    )

    assert len(scores) == 3
    assert scores[0] > scores[1]
    assert scores[2] > scores[1]


def test_fake_models_empty_query():
    client = FakeModelsClient()

    scores = client.rerank("", ["First text", "Second text"])

    assert scores == [0.0, 0.0]


def test_fake_models_preserve_input_order():
    client = FakeModelsClient()

    texts = ["tax declaration", "weather forecast"]
    embeddings = client.embed(texts)

    assert embeddings[0] == client.embed([texts[0]])[0]
    assert embeddings[1] == client.embed([texts[1]])[0]
