import importlib.util
from pathlib import Path

import httpx
from fastapi.testclient import TestClient


# Load services/cloud-gateway/app.py despite the hyphen in its directory name.
APP_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "cloud-gateway"
    / "app.py"
)
SPEC = importlib.util.spec_from_file_location("cloud_gateway_app", APP_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)

REAL_ASYNC_CLIENT = httpx.AsyncClient


def configure_provider(monkeypatch):
    monkeypatch.setenv(
        "CLOUD_API_BASE",
        "https://generativelanguage.googleapis.com/v1beta/openai",
    )
    monkeypatch.setenv("CLOUD_API_KEY", "fake-test-key")
    monkeypatch.setenv("CLOUD_MODEL", "gemini-test-model")


def install_transport(monkeypatch, handler):
    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", client_factory)


def test_health():
    response = TestClient(gateway.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_forwards_request_and_enforces_configured_model(monkeypatch):
    configure_provider(monkeypatch)
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = __import__("json").loads(request.content)

        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Réponse simulée"}}
                ]
            },
        )

    install_transport(monkeypatch, handler)

    response = TestClient(gateway.app).post(
        "/v1/chat/completions",
        json={
            "model": "model-imposé-par-le-client",
            "messages": [{"role": "user", "content": "Bonjour"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Réponse simulée"
    assert captured["url"].endswith("/v1beta/openai/chat/completions")
    assert captured["authorization"] == "Bearer fake-test-key"
    assert captured["payload"]["model"] == "gemini-test-model"


def test_chat_returns_502_when_provider_fails(monkeypatch):
    configure_provider(monkeypatch)

    def handler(request):
        return httpx.Response(429, json={"error": "simulated error"})

    install_transport(monkeypatch, handler)

    response = TestClient(gateway.app).post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Bonjour"}],
        },
    )

    assert response.status_code == 502
    assert "fake-test-key" not in response.text


class FakeSSEStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Bonjour"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        pass

def test_stream_forwards_server_sent_events(monkeypatch):
    configure_provider(monkeypatch)
    captured = {}

    def handler(request):
        captured["payload"] = __import__("json").loads(request.content)

        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=FakeSSEStream(),
        )

    install_transport(monkeypatch, handler)

    response = TestClient(gateway.app).post(
        "/v1/chat/completions",
        json={
            "stream": True,
            "messages": [{"role": "user", "content": "Bonjour"}],
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "Bonjour" in response.text
    assert "data: [DONE]" in response.text
    assert captured["payload"]["model"] == "gemini-test-model"


def test_count_tokens_uses_gemini_native_endpoint(monkeypatch):
    configure_provider(monkeypatch)
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["payload"] = __import__("json").loads(request.content)

        return httpx.Response(200, json={"totalTokens": 42})

    install_transport(monkeypatch, handler)

    response = TestClient(gateway.app).post(
        "/count_tokens",
        json={"text": "Texte à compter"},
    )

    assert response.status_code == 200
    assert response.json() == {"count": 42}
    assert "/v1beta/models/gemini-test-model:countTokens" in captured["url"]
    assert "key=fake-test-key" in captured["url"]
    assert captured["payload"]["contents"][0]["parts"][0]["text"] == "Texte à compter"


def test_missing_provider_configuration_returns_503(monkeypatch):
    monkeypatch.delenv("CLOUD_API_BASE", raising=False)
    monkeypatch.delenv("CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("CLOUD_MODEL", raising=False)

    response = TestClient(gateway.app).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Bonjour"}]},
    )

    assert response.status_code == 503
    assert "not configured" in response.text


def test_count_tokens_rejects_non_gemini_provider(monkeypatch):
    configure_provider(monkeypatch)
    monkeypatch.setenv("CLOUD_API_BASE", "https://api.example.com/v1")

    response = TestClient(gateway.app).post(
        "/count_tokens",
        json={"text": "Texte à compter"},
    )

    assert response.status_code == 501

