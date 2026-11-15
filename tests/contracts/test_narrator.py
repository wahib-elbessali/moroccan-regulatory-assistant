"""Contract tests for P4's Narrator Protocol (00-shared §6.6, §9)."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator

import pytest

from src.core.contracts import ProcessEvent, StepType
from src.core.contracts.fakes.answer import FakeNarrator


def _process_event(step: StepType) -> ProcessEvent:
    data_by_step = {
        StepType.PLAN: {"sub_questions": ["question 1", "question 2"]},
        StepType.SEARCH: {"query": "test query", "count": 2, "titles": ["title 1"]},
        StepType.GRADE: {"relevant": 1, "total": 2, "kept": ["title — article"]},
        StepType.REFORMULATE: {
            "old_query": "old query",
            "new_query": "new query",
            "iteration": 2,
        },
        StepType.WEB: {"status": "done", "count": 2, "by_user": False},
        StepType.WRITE: {},
        StepType.VERIFY: {"supported": 1, "total": 2, "reasons": ["not_supported"]},
    }
    return ProcessEvent(step=step, data=data_by_step[step])


def _template_narrator():
    """Use the real deterministic narrator once P4 implements it."""
    try:
        module = importlib.import_module("src.agents.answer.narrator")
    except ModuleNotFoundError as exc:
        if exc.name != "src.agents.answer.narrator":
            raise
        pytest.skip("TemplateNarrator does not exist yet")
    narrator_type = getattr(module, "TemplateNarrator", None)
    if narrator_type is None:
        pytest.skip("TemplateNarrator does not exist yet")
    return narrator_type()


async def _collect(narrator, event: ProcessEvent, language: str) -> list[str]:
    pieces: list[str] = []
    stream: AsyncIterator[str] = narrator.narrate(event, language)
    async for piece in stream:
        pieces.append(piece)
    return pieces


@pytest.mark.parametrize("narrator_kind", ["fake", "template"])
def test_t23_every_step_has_bilingual_nonempty_template(narrator_kind: str) -> None:
    narrator = FakeNarrator() if narrator_kind == "fake" else _template_narrator()

    for step in StepType:
        event = _process_event(step)
        for language in ("fr", "ar"):
            pieces = asyncio.run(_collect(narrator, event, language))
            assert pieces
            assert all(piece.strip() for piece in pieces)


@pytest.mark.parametrize(
    ("event_data", "expected"),
    [
        (
            {"status": "skipped", "count": 0, "by_user": False},
            "Recherche web non effectuée.",
        ),
        (
            {"status": "skipped", "count": 0, "by_user": True},
            "Recherche web désactivée, à votre demande.",
        ),
    ],
)
def test_web_skip_templates_do_not_reveal_reason(event_data: dict, expected: str) -> None:
    event = ProcessEvent(step=StepType.WEB, data=event_data)
    pieces = asyncio.run(_collect(FakeNarrator(), event, "fr"))

    assert pieces == [expected]


def test_verify_template_uses_counts_and_not_reason_text() -> None:
    event = ProcessEvent(
        step=StepType.VERIFY,
        data={"supported": 2, "total": 3, "reasons": ["excerpt_not_found"]},
    )
    pieces = asyncio.run(_collect(FakeNarrator(), event, "fr"))

    assert pieces == ["3 affirmation(s) vérifiée(s) : 2 appuyée(s) par une source."]
