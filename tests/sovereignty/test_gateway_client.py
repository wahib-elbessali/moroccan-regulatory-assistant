"""P6-11, P6-14: ``GatewayClient`` exists only with both switches on, then talks to the gateway."""

import json

import httpx
import pytest

from src.core.contracts.errors import ServiceError
from src.core.llm.gateway import GatewayClient, cloud_allowed
from src.core.llm.ollama import OllamaClient

ALLOWED = {"ALLOW_CLOUD_LLM": "true"}


@pytest.mark.parametrize(
    ("mode", "environ"),
    [
        ("local", ALLOWED),  # permission given, but not in cloud mode
        ("light", ALLOWED),
        ("cloud", {}),  # cloud mode, but no permission (T14)
        ("cloud", {"ALLOW_CLOUD_LLM": "false"}),
        ("cloud", {"ALLOW_CLOUD_LLM": "1"}),
        ("cloud", {"ALLOW_CLOUD_LLM": "yes"}),
        ("cloud", {"ALLOW_CLOUD_LLM": ""}),
    ],
)
def test_the_client_is_refused_unless_both_switches_are_on(
    mode: str, environ: dict[str, str]
) -> None:
    assert not cloud_allowed(mode, environ)
    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        GatewayClient(mode, model="m", num_ctx=512, environ=environ)


@pytest.mark.parametrize("value", ["true", "TRUE", " true "])
def test_the_client_is_created_with_both_switches_on(value: str) -> None:
    client = GatewayClient("cloud", model="m", num_ctx=512, environ={"ALLOW_CLOUD_LLM": value})
    assert client.model == "m"


def test_the_refusal_happens_before_any_network_call() -> None:
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    with pytest.raises(ServiceError):
        GatewayClient(
            "cloud",
            model="m",
            num_ctx=512,
            environ={},
            client=httpx.Client(transport=httpx.MockTransport(record), base_url="http://x"),
        )
    assert calls == []


def test_chat_goes_to_the_gateway_with_the_app_settings() -> None:
    calls: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message": {"content": "réponse"}, "done": True})

    http = httpx.Client(transport=httpx.MockTransport(gateway), base_url="http://cloud-gateway")
    client = GatewayClient("cloud", model="m", num_ctx=512, environ=ALLOWED, client=http)

    assert client.chat([{"role": "user", "content": "q"}], max_tokens=20) == "réponse"
    body = json.loads(calls[0].content)
    assert calls[0].url.path == "/api/chat"
    assert body["model"] == "m"
    assert body["options"] == {"num_ctx": 512, "temperature": 0.0, "num_predict": 20}


def test_an_unreachable_gateway_is_a_service_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.Client(transport=httpx.MockTransport(down), base_url="http://cloud-gateway")
    client = GatewayClient("cloud", model="m", num_ctx=512, environ=ALLOWED, client=http)
    with pytest.raises(ServiceError):
        client.chat([{"role": "user", "content": "q"}])


def _ndjson(*chunks: dict) -> httpx.Response:
    lines = [json.dumps(c, ensure_ascii=False) for c in chunks]
    return httpx.Response(200, content=("\n".join(lines) + "\n").encode("utf-8"))


async def _collect(client: GatewayClient, **kwargs: object) -> list[str]:
    messages = [{"role": "user", "content": "q"}]
    return [piece async for piece in client.stream(messages, **kwargs)]  # type: ignore[arg-type]


def _async(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://cloud-gateway"
    )


@pytest.mark.asyncio
async def test_stream_goes_to_the_gateway_piece_by_piece() -> None:
    calls: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ndjson(
            {"message": {"content": "شروط "}, "done": False},
            {"message": {"content": "الكفالة"}, "done": False},
            {"message": {"content": ""}, "done": True},
        )

    client = GatewayClient(
        "cloud", model="m", num_ctx=512, environ=ALLOWED, async_client=_async(gateway)
    )
    assert await _collect(client) == ["شروط ", "الكفالة"]
    assert json.loads(calls[0].content)["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "cloud provider not configured"}),
        _ndjson({"error": "cloud provider unreachable"}),
        _ndjson({"message": {"content": "x"}, "done": False}),  # ends without done
    ],
)
async def test_stream_failures_are_service_errors(response: httpx.Response) -> None:
    client = GatewayClient(
        "cloud", model="m", num_ctx=512, environ=ALLOWED, async_client=_async(lambda r: response)
    )
    with pytest.raises(ServiceError):
        await _collect(client)


class LocalRecorder(OllamaClient):
    """Stands for the local Ollama: records the calls, never touches the network."""

    def __init__(self) -> None:
        super().__init__("http://llm:11434", model="narr", num_ctx=512)
        self.calls: list[str] = []

    def chat(self, messages, *, model=None, max_tokens=None, temperature=0.0) -> str:
        self.calls.append(f"chat:{model}")
        return "local"

    async def stream(self, messages, *, model=None, max_tokens=None):
        self.calls.append(f"stream:{model}")
        yield "local"


def _never(request: httpx.Request) -> httpx.Response:
    raise AssertionError("the narration model must not reach the gateway")


@pytest.mark.asyncio
async def test_the_narration_model_stays_local() -> None:
    local = LocalRecorder()
    client = GatewayClient(
        "cloud",
        model="answer",
        num_ctx=512,
        environ=ALLOWED,
        local=local,
        narration_model="narr",
        client=httpx.Client(transport=httpx.MockTransport(_never), base_url="http://g"),
        async_client=_async(_never),
    )
    assert client.chat([{"role": "user", "content": "q"}], model="narr") == "local"
    assert await _collect(client, model="narr") == ["local"]
    assert local.calls == ["chat:narr", "stream:narr"]


def test_the_answer_model_goes_to_the_gateway_not_to_the_local_ollama() -> None:
    local = LocalRecorder()
    calls: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message": {"content": "cloud"}, "done": True})

    client = GatewayClient(
        "cloud",
        model="answer",
        num_ctx=512,
        environ=ALLOWED,
        local=local,
        narration_model="narr",
        client=httpx.Client(transport=httpx.MockTransport(gateway), base_url="http://g"),
    )
    assert client.chat([{"role": "user", "content": "q"}]) == "cloud"
    assert client.chat([{"role": "user", "content": "q"}], model="answer") == "cloud"
    assert local.calls == [] and len(calls) == 2
