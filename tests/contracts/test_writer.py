"""Contract tests for P4's Writer Protocol (00-shared §6.6, §9)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.core.contracts import (  # noqa: E402
    AnswerStatus,
    UserContext,
    Writer,
)
from src.core.contracts.fakes.answer import FakeWriter  # noqa: E402


def _real_writer() -> Writer:
    """Return P4's real writer, or skip until its implementation lands."""
    module = importlib.import_module("src.agents.answer")
    factory: Callable[[], Writer] | None = getattr(module, "real_writer", None)
    if factory is None:
        pytest.skip("real_writer() does not exist yet")
    return factory()


@pytest.fixture(params=["fake", "real"])
def writer(request: pytest.FixtureRequest) -> Writer:
    if request.param == "fake":
        return FakeWriter()
    return _real_writer()


@pytest.fixture
def reader_ctx() -> UserContext:
    """Synthetic test context; it does not authenticate a real user."""
    return UserContext(
        user_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        username="contract-reader",
        role="lecteur",
        web_enabled=False,
        request_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    )


def test_t1_no_sources_returns_unknown_without_llm_call(
    writer: Writer, reader_ctx: UserContext
) -> None:
    answer = writer.write(
        question="Quelle est la règle applicable ?",
        passages=[],
        web=[],
        ctx=reader_ctx,
    )

    assert answer.status == AnswerStatus.UNKNOWN
    assert answer.text == (
        "Je n'ai pas trouvé cette information dans les documents auxquels vous avez accès."
    )
    assert answer.citations == []
    assert answer.confidence == 0.0
    assert answer.language == "fr"


def test_t16_emits_one_verify_event_for_available_source(
    writer: Writer, reader_ctx: UserContext, sample_chunks
) -> None:
    from src.core.contracts import Passage, ProcessEvent, StepType  # noqa: PLC0415

    passage = Passage(chunk=sample_chunks[0], score=1.0, rank=1)
    events: list[ProcessEvent] = []

    answer = writer.write(
        question="ما هي القاعدة؟",
        passages=[passage],
        web=[],
        ctx=reader_ctx,
        emit=events.append,
    )

    assert answer.language == "ar"
    assert len(events) == 1
    assert events[0].step == StepType.VERIFY
    assert set(events[0].data) == {"supported", "total", "reasons"}
    assert events[0].data["supported"] >= 0
    assert events[0].data["total"] >= 0
    assert set(events[0].data["reasons"]).issubset(
        {"no_citation", "not_supported", "excerpt_not_found"}
    )


def test_fake_writer_cites_first_passage(reader_ctx: UserContext, sample_chunks) -> None:
    from src.core.contracts import Passage  # noqa: PLC0415

    first = Passage(chunk=sample_chunks[0], score=1.0, rank=1)
    second = Passage(chunk=sample_chunks[1], score=0.5, rank=2)

    answer = FakeWriter().write(
        question="Quelle est la règle applicable ?",
        passages=[first, second],
        web=[],
        ctx=reader_ctx,
    )

    assert answer.status == AnswerStatus.ANSWERED
    assert answer.citations[0].doc_id == first.chunk.doc_id
    assert answer.citations[0].excerpt == first.chunk.text
    assert "[1]" in answer.text
