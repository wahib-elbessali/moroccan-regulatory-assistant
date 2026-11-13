"""Acceptance tests for P4's real template and LLM narrators."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from src.agents.answer.narrator import LLMNarrator, TemplateNarrator, real_narrator
from src.core.contracts import ProcessEvent, StepType


def _collect(narrator, event: ProcessEvent, language: str) -> list[str]:
    async def collect() -> list[str]:
        return [piece async for piece in narrator.narrate(event, language)]

    return asyncio.run(collect())


@pytest.mark.parametrize(
    ("by_user", "expected_fr", "expected_ar"),
    [
        (
            False,
            "Recherche web non effectuée.",
            "لم يُجرَ البحث عبر الويب.",
        ),
        (
            True,
            "Recherche web désactivée, à votre demande.",
            "تم إيقاف البحث عبر الويب بناءً على اختيارك.",
        ),
    ],
)
def test_t19_t20_web_skip_templates_are_fixed_for_both_narrators(
    by_user, expected_fr, expected_ar, monkeypatch
) -> None:
    event = ProcessEvent(
        step=StepType.WEB,
        data={"status": "skipped", "count": 0, "by_user": by_user, "reason": "private"},
    )
    unexpected_calls = []

    def unexpected_llm():
        unexpected_calls.append(True)
        raise AssertionError("web narration must not call the LLM")

    monkeypatch.setattr("src.agents.answer.narrator.get_llm", unexpected_llm)
    for narrator in (TemplateNarrator(), LLMNarrator()):
        assert _collect(narrator, event, "fr") == [expected_fr]
        assert _collect(narrator, event, "ar") == [expected_ar]

    assert unexpected_calls == []


def test_t21_llm_narrator_falls_back_to_template_when_stream_raises(monkeypatch) -> None:
    class BrokenStream:
        def stream(self, messages, *, model=None, max_tokens=None) -> AsyncIterator[str]:
            async def generate() -> AsyncIterator[str]:
                raise RuntimeError("stream unavailable")
                yield ""

            return generate()

    monkeypatch.setattr("src.agents.answer.narrator.get_llm", lambda: BrokenStream())
    event = ProcessEvent(step=StepType.SEARCH, data={"query": "test", "count": 2, "titles": []})

    assert _collect(LLMNarrator(), event, "fr") == ["Recherche « test » : 2 passage(s) trouvé(s)."]


def test_llm_narrator_streams_with_configured_model_and_token_limit(monkeypatch) -> None:
    class RecordingStream:
        def __init__(self) -> None:
            self.calls = []

        def stream(self, messages, *, model=None, max_tokens=None) -> AsyncIterator[str]:
            self.calls.append((messages, model, max_tokens))

            async def generate() -> AsyncIterator[str]:
                yield "Je prépare "
                yield "la recherche."

            return generate()

    llm = RecordingStream()

    def configured(section: str, key: str, default):
        values = {
            ("llm", "narration_model"): "narration-test-model",
            ("answer", "narration_max_tokens"): 42,
        }
        return values.get((section, key), default)

    monkeypatch.setattr("src.agents.answer.narrator.get_llm", lambda: llm)
    monkeypatch.setattr("src.agents.answer.narrator.setting", configured)
    event = ProcessEvent(step=StepType.SEARCH, data={"query": "test", "count": 2, "titles": []})

    assert _collect(LLMNarrator(), event, "fr") == ["Je prépare ", "la recherche."]
    messages, model, max_tokens = llm.calls[0]
    assert model == "narration-test-model"
    assert max_tokens == 42
    assert "French" in messages[0]["content"]
    assert '"step":"search"' in messages[1]["content"]
    assert '"count":2' in messages[1]["content"]


def test_t22_real_narrator_selects_template_in_light_mode(monkeypatch) -> None:
    monkeypatch.setattr("src.agents.answer.narrator.app_mode", lambda: "light")

    assert isinstance(real_narrator(), TemplateNarrator)


def test_real_narrator_selects_llm_outside_light_mode(monkeypatch) -> None:
    monkeypatch.setattr("src.agents.answer.narrator.app_mode", lambda: "local")

    assert isinstance(real_narrator(), LLMNarrator)


def test_t23_template_narrator_covers_every_step_in_french_and_arabic() -> None:
    data_by_step = {
        StepType.PLAN: {"sub_questions": ["one"]},
        StepType.SEARCH: {"query": "test", "count": 1, "titles": []},
        StepType.GRADE: {"relevant": 1, "total": 1, "kept": []},
        StepType.REFORMULATE: {"new_query": "test reformulated"},
        StepType.WEB: {"status": "done", "count": 1, "by_user": False},
        StepType.WRITE: {},
        StepType.VERIFY: {"supported": 1, "total": 1, "reasons": []},
    }

    for step, data in data_by_step.items():
        for language in ("fr", "ar"):
            pieces = _collect(TemplateNarrator(), ProcessEvent(step=step, data=data), language)
            assert len(pieces) == 1
            assert pieces[0].strip()
