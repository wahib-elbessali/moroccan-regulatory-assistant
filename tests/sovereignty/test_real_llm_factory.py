"""P6-08: ``real_llm()`` serves the light model in ``light`` mode and the main one otherwise."""

from types import SimpleNamespace

import pytest

from src.core import config
from src.core.llm import real_llm
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
    [("local", "main-model"), ("light", "light-model"), ("cloud", "main-model")],
)
def test_real_llm_picks_the_model_from_the_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: str
) -> None:
    monkeypatch.setattr(config, "cfg", _config(mode))

    client = real_llm()

    assert isinstance(client, OllamaClient)
    assert client.model == expected
    assert client.num_ctx == 4096
