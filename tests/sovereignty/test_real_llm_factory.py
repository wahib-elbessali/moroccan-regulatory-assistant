"""P6-08, P6-14: ``real_llm()`` serves the model of the mode; ``cloud`` mode needs its permission."""

from types import SimpleNamespace

import pytest

from src.core import config
from src.core.contracts.errors import ServiceError
from src.core.llm import real_llm
from src.core.llm.gateway import GATEWAY_URL, GatewayClient
from src.core.llm.ollama import OllamaClient


def _config(mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        mode=mode,
        llm=SimpleNamespace(
            base_url="http://llm:11434",
            model="main-model",
            model_light="light-model",
            narration_model="narration-model",
            num_ctx=4096,
        ),
    )


@pytest.mark.parametrize(("mode", "expected"), [("local", "main-model"), ("light", "light-model")])
def test_real_llm_picks_the_model_from_the_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: str
) -> None:
    monkeypatch.setattr(config, "cfg", _config(mode))

    client = real_llm()

    assert type(client) is OllamaClient
    assert client.model == expected
    assert client.num_ctx == 4096


def test_t14_cloud_mode_without_permission_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """T14: ``mode = cloud`` and no ``ALLOW_CLOUD_LLM`` -> ``ServiceError`` from ``get_llm``."""
    monkeypatch.setattr(config, "cfg", _config("cloud"))
    monkeypatch.delenv("ALLOW_CLOUD_LLM", raising=False)

    with pytest.raises(ServiceError, match="cloud mode not allowed"):
        real_llm()


def test_cloud_mode_with_permission_goes_through_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "cfg", _config("cloud"))
    monkeypatch.setenv("ALLOW_CLOUD_LLM", "true")

    client = real_llm()

    assert isinstance(client, GatewayClient)
    assert client.base_url == GATEWAY_URL
    assert (client.model, client.num_ctx) == ("main-model", 4096)
    assert client.narration_model == "narration-model"
    assert isinstance(client.local, OllamaClient)
    assert (client.local.base_url, client.local.model) == ("http://llm:11434", "narration-model")
