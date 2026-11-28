"""Tests of cloud-gateway (services/cloud-gateway/app.py) against a fake provider: nothing leaves.

The module is loaded by path under its own name: web-search's tests also have an ``app`` module.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

APP_PATH = Path(__file__).resolve().parents[3] / "services" / "cloud-gateway" / "app.py"
_spec = importlib.util.spec_from_file_location("cloud_gateway_app", APP_PATH)
gw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw)

PROVIDER = {
    "CLOUD_API_BASE": "https://provider.test/v1/",
    "CLOUD_API_KEY": "test-key",
    "CLOUD_MODEL": "cloud-model",
}
ASK = {
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "question"}],
    "options": {"num_ctx": 16384, "temperature": 0.0, "num_predict": 50},
}


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch):
    """Configures the provider and replaces it with a recorder; ``reply`` sets what it answers."""
    for key, value in PROVIDER.items():
        monkeypatch.setenv(key, value)
    state = {
        "requests": [],
        "reply": httpx.Response(200, json={"choices": [{"message": {"content": "réponse"}}]}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        reply = state["reply"]
        if isinstance(reply, Exception):
            raise reply
        return reply

    real = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(gw.httpx, "AsyncClient", fake_client)
    return state


@pytest.fixture
def client() -> TestClient:
    return TestClient(gw.app)


@pytest.mark.parametrize("missing", list(PROVIDER))
def test_without_a_complete_provider_nothing_is_sent(
    client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)
    response = client.post("/api/chat", json={**ASK, "stream": False})
    assert response.status_code == 503
    assert provider["requests"] == []
    assert client.get("/health").json() == {"status": "ok", "provider_configured": False}


def test_a_chat_is_translated_to_the_provider_and_back(client: TestClient, provider: dict) -> None:
    response = client.post("/api/chat", json={**ASK, "stream": False})

    assert response.status_code == 200
    assert response.json() == {"message": {"role": "assistant", "content": "réponse"}, "done": True}
    sent = provider["requests"][0]
    assert str(sent.url) == "https://provider.test/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer test-key"
    assert json.loads(sent.content) == {
        "model": "cloud-model",
        "messages": [{"role": "user", "content": "question"}],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": 50,
    }


def test_a_stream_comes_back_as_ollama_lines(client: TestClient, provider: dict) -> None:
    sse = (
        'data: {"choices":[{"delta":{"content":"شروط "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"الكفالة"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider["reply"] = httpx.Response(200, content=sse.encode())

    with client.stream("POST", "/api/chat", json={**ASK, "stream": True}) as response:
        lines = [json.loads(line) for line in response.iter_lines() if line]

    assert [x["message"]["content"] for x in lines] == ["شروط ", "الكفالة", ""]
    assert [x["done"] for x in lines] == [False, False, True]


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(401, json={"error": "bad key"}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.ConnectError("down"),
    ],
)
def test_provider_failures_are_502(client: TestClient, provider: dict, reply) -> None:
    provider["reply"] = reply
    response = client.post("/api/chat", json={**ASK, "stream": False})
    assert response.status_code == 502
    assert "error" in response.json()


def test_nothing_of_the_prompt_or_answer_is_logged(
    client: TestClient, provider: dict, caplog: pytest.LogCaptureFixture
) -> None:
    secret_question = {
        **ASK,
        "messages": [{"role": "user", "content": "texte interne confidentiel"}],
    }
    with caplog.at_level("INFO", logger="cloud_gateway"):
        client.post("/api/chat", json={**secret_question, "stream": False})
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert '"status": "ok"' in logs
    assert "confidentiel" not in logs and "réponse" not in logs and "test-key" not in logs


@pytest.mark.parametrize(
    ("extra", "sent"), [(None, 50), ("0", 50), ("1400", 1450), ("bad", 50), ("-5", 50)]
)
def test_reasoning_tokens_are_added_to_max_tokens(
    client: TestClient, provider: dict, monkeypatch: pytest.MonkeyPatch, extra, sent: int
) -> None:
    """A thinking model needs room for hidden reasoning on top of what the app asks for."""
    if extra is None:
        monkeypatch.delenv("CLOUD_REASONING_TOKENS", raising=False)
    else:
        monkeypatch.setenv("CLOUD_REASONING_TOKENS", extra)
    client.post("/api/chat", json={**ASK, "stream": False})
    assert json.loads(provider["requests"][0].content)["max_tokens"] == sent
