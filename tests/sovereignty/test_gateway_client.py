"""Unit tests for GatewayClient, using an HTTP mock (no real cloud calls)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from src.core import config
from src.core.contracts.errors import ServiceError
from src.core.llm import gateway

MESSAGES = [{"role": "user", "content": "Quelle est la règle fiscale ?"}]
ANSWER = "Voici la réponse."


class Recorder:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(
            200,
            json={"choices": [{"message": {"content": ANSWER}}]},
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def _client(
    monkeypatch: pytest.MonkeyPatch,
    handler: object,
    *,
    mode: str = "cloud",
    allowed: str = "true",
) -> gateway.GatewayClient:
    monkeypatch.setattr(config, "cfg", SimpleNamespace(mode=mode))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", allowed)

    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return gateway.GatewayClient(
        client=httpx.Client(base_url="http://cloud-gateway:8000", transport=transport),
        async_client=httpx.AsyncClient(base_url="http://cloud-gateway:8000", transport=transport),
    )


def test_cloud_guard_refuses_local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "cfg", SimpleNamespace(mode="local"))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", "true")

    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        gateway.GatewayClient()


@pytest.mark.parametrize("allowed", ["false", "False", ""])
def test_cloud_guard_refuses_without_explicit_permission(
    monkeypatch: pytest.MonkeyPatch, allowed: str
) -> None:
    monkeypatch.setattr(config, "cfg", SimpleNamespace(mode="cloud"))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", allowed)

    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        gateway.GatewayClient()


def test_chat_returns_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()
    client = _client(monkeypatch, recorder)

    assert client.chat(MESSAGES) == ANSWER


def test_chat_sends_openai_compatible_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    client = _client(monkeypatch, recorder)

    client.chat(MESSAGES, model="gemini-test", max_tokens=80, temperature=0.2)

    [request] = recorder.requests
    body = json.loads(request.content)
    assert (request.method, request.url.path) == ("POST", "/v1/chat/completions")
    assert body == {
        "messages": MESSAGES,
        "temperature": 0.2,
        "stream": False,
        "model": "gemini-test",
        "max_tokens": 80,
    }


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_chat_http_error_is_service_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    client = _client(
        monkeypatch,
        Recorder(httpx.Response(status, json={"error": "provider error"})),
    )

    with pytest.raises(ServiceError):
        client.chat(MESSAGES)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    ],
)
def test_chat_invalid_response_is_service_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    client = _client(monkeypatch, Recorder(response))

    with pytest.raises(ServiceError):
        client.chat(MESSAGES)


def test_chat_unreachable_gateway_is_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(monkeypatch, down)

    with pytest.raises(ServiceError):
        client.chat(MESSAGES)


async def _collect(client: gateway.GatewayClient) -> list[str]:
    return [piece async for piece in client.stream(MESSAGES)]


@pytest.mark.asyncio
async def test_stream_yields_sse_pieces_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        'data: {"choices":[{"delta":{"content":"Bonjour "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Gemini"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    recorder = Recorder(httpx.Response(200, text=content))
    client = _client(monkeypatch, recorder)

    assert await _collect(client) == ["Bonjour ", "Gemini"]


@pytest.mark.asyncio
async def test_stream_passes_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    recorder = Recorder(httpx.Response(200, text=content))
    client = _client(monkeypatch, recorder)

    assert await _collect(client) == ["ok"]
    body = json.loads(recorder.requests[0].content)
    assert body["stream"] is True
    assert body["temperature"] == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="data: not-json\n\ndata: [DONE]\n\n"),
        httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":123}}]}\n\ndata: [DONE]\n\n',
        ),
        httpx.Response(200, text='data: {"choices":[{"delta":{"content":"x"}}]}\n\n'),
    ],
)
async def test_stream_failure_is_service_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    client = _client(monkeypatch, Recorder(response))

    with pytest.raises(ServiceError):
        await _collect(client)


def test_count_tokens_uses_gateway_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder(httpx.Response(200, json={"count": 42}))
    client = _client(monkeypatch, recorder)

    assert client.count_tokens("Bonjour Gemini") == 42
    [request] = recorder.requests
    assert request.url.path == "/count_tokens"
    assert json.loads(request.content) == {"text": "Bonjour Gemini"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"count": -1}),
        httpx.Response(200, json={"count": "42"}),
        httpx.Response(200, json={"count": True}),
    ],
)
def test_count_tokens_invalid_response_is_service_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    client = _client(monkeypatch, Recorder(response))

    with pytest.raises(ServiceError):
        client.count_tokens("Bonjour Gemini")
