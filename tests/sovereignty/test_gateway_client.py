"""P6-11, P6-14: ``GatewayClient`` exists only with both switches on, then talks to the gateway."""

import json

import httpx
import pytest

from src.core.contracts.errors import ServiceError
from src.core.llm.gateway import GatewayClient, cloud_allowed

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
