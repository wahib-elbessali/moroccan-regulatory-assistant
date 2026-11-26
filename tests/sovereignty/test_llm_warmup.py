"""``make warm`` loads the answer model of the mode and the narration model, once each."""

import pytest

from src.core.contracts.errors import ServiceError
from src.core.llm import warmup


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("local", ["big", "narr"]), ("light", ["small", "narr"]), ("cloud", ["big", "narr"])],
)
def test_models_to_load(mode: str, expected: list[str]) -> None:
    assert warmup.models_to_load(mode, "big", "small", "narr") == expected


def test_the_same_model_is_loaded_once() -> None:
    assert warmup.models_to_load("light", "big", "small", "small") == ["small"]


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail = fail

    def chat(self, messages: list[dict], *, model: str, max_tokens: int) -> str:
        if self.fail:
            raise ServiceError("llm service unavailable")
        self.calls.append((model, max_tokens))
        return "ok"


@pytest.fixture
def light_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import src.core.config as config

    llm = SimpleNamespace(model="big", model_light="small", narration_model="narr")
    monkeypatch.setattr(config, "cfg", SimpleNamespace(mode="light", llm=llm))


def test_main_sends_one_short_request_per_model(
    light_config: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Recorder()
    monkeypatch.setattr("src.core.llm.real_llm", lambda: client)
    assert warmup.main() == 0
    assert client.calls == [("small", 1), ("narr", 1)]


def test_main_fails_when_a_model_does_not_load(
    light_config: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.core.llm.real_llm", lambda: Recorder(fail=True))
    assert warmup.main() == 1
