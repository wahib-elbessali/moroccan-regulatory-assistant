"""P6: real_llm() selects the correct client for each application mode."""

from types import SimpleNamespace

import pytest

from src.core import config
from src.core.contracts import registry
from src.core.contracts.errors import ServiceError
from src.core.llm import real_llm
from src.core.llm.gateway import GatewayClient
from src.core.llm.ollama import OllamaClient


def _config(mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        mode=mode,
        llm=SimpleNamespace(
            base_url="http://llm:11434",
            model="main-model",
            model_light="light-model",
            num_ctx=4096,
        ),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("local", "main-model"), ("light", "light-model")],
)
def test_real_llm_picks_the_ollama_model(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: str
) -> None:
    monkeypatch.setattr(config, "cfg", _config(mode))

    client = real_llm()

    assert isinstance(client, OllamaClient)
    assert client.model == expected
    assert client.num_ctx == 4096


def test_real_llm_returns_gateway_client_in_authorized_cloud_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "cfg", _config("cloud"))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", "true")

    client = real_llm()

    assert isinstance(client, GatewayClient)


@pytest.mark.parametrize("allow_cloud", ["false", "", "TRUE"])
def test_real_llm_refuses_cloud_without_exact_permission(
    monkeypatch: pytest.MonkeyPatch, allow_cloud: str
) -> None:
    monkeypatch.setattr(config, "cfg", _config("cloud"))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", allow_cloud)

    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        real_llm()


def test_t14_registry_refuses_cloud_without_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T14: get_llm() must refuse cloud mode without explicit authorization."""
    cloud_cfg = SimpleNamespace(
        mode="cloud",
        contracts={"llm": "real"},
    )

    # The registry and GatewayClient must see the same cloud configuration.
    monkeypatch.setattr(config, "cfg", cloud_cfg)
    monkeypatch.setattr(registry, "cfg", cloud_cfg)
    monkeypatch.delenv("ALLOW_CLOUD_LLM", raising=False)

    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        registry.get_llm()
