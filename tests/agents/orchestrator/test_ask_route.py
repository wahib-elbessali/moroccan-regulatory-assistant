"""Tests of the real POST /ask route (P3-28 to P3-31), with the FakeOrchestrator.

The contract test (tests/contracts/test_orchestrator.py) already covers T21 and T22 on the happy
path. Here: SSE format, use_web pass-through, and the error cases.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api.routes.ask import router
from src.core.contracts import registry
from src.core.contracts.errors import AppError, ServiceError
from src.core.contracts.fakes.orchestrator import FakeOrchestrator
from src.core.security import get_current_user_context

SECRET_QUESTION = "سؤال سري جدا"


class _SpyAudit:
    def __init__(self):
        self.calls = []

    def log_query(self, request_id, user_id, query, latency_ms):
        self.calls.append((request_id, user_id, query, latency_ms))

    def log_action(self, *a, **k):
        pass


@pytest.fixture
def audit():
    spy = _SpyAudit()
    registry.override("audit", spy)
    return spy


@pytest.fixture
def client(lecteur_ctx, audit):
    registry.override("orchestrator", FakeOrchestrator())
    app = FastAPI()
    app.include_router(router, prefix="/ask")
    app.dependency_overrides[get_current_user_context] = lambda: lecteur_ctx

    @app.exception_handler(AppError)
    async def _app_error(request, exc):
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=exc.http_status)

    yield TestClient(app)
    registry.reset()


def _events(raw: str) -> list[tuple[str, dict]]:
    out = []
    for block in raw.strip().split("\n\n"):
        event_line, data_line = block.split("\n")
        out.append(
            (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        )
    return out


def test_done_is_last_and_has_request_id_and_latency(client, lecteur_ctx):
    events = _events(client.post("/ask", json={"question": "Quel est le délai ?"}).text)
    kind, data = events[-1]
    assert kind == "done"
    assert data["request_id"] == str(lecteur_ctx.request_id)
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert [k for k, _ in events].count("done") == 1


def test_answer_is_a_valid_answer_with_citation(client):
    events = _events(client.post("/ask", json={"question": "Quel est le délai ?"}).text)
    answer = dict(events)["answer"]
    assert answer["language"] == "fr"
    assert "[1]" in answer["text"] and len(answer["citations"]) == 1


def test_arabic_text_is_not_escaped_in_the_stream(client):
    raw = client.post("/ask", json={"question": "ما هو أجل الطعن؟"}).text
    assert "أقوم بتقسيم السؤال" in raw


def test_use_web_is_passed_unchanged(client):
    seen = []

    class Spy(FakeOrchestrator):
        async def run(self, question, ctx, use_web=True):
            seen.append(use_web)
            async for e in super().run(question, ctx, use_web):
                yield e

    registry.override("orchestrator", Spy())
    client.post("/ask", json={"question": "Quel est le délai ?", "use_web": False})
    client.post("/ask", json={"question": "Quel est le délai ?"})
    assert seen == [False, True]


@pytest.mark.parametrize("question", ["", "   ", "؟؟", "ا" * 1001])
def test_invalid_question_is_422_and_not_audited(client, audit, question):
    r = client.post("/ask", json={"question": question})
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_input"
    assert audit.calls == []


def test_missing_question_field_is_422(client):
    assert client.post("/ask", json={}).status_code == 422


def test_question_of_exactly_max_length_is_accepted(client):
    assert client.post("/ask", json={"question": "ا" * 1000}).status_code == 200


@pytest.mark.parametrize(
    "exc,code",
    [
        (RuntimeError(SECRET_QUESTION), "service_error"),
        (ServiceError(SECRET_QUESTION), "service_error"),
    ],
)
def test_orchestrator_failure_gives_error_then_done(client, audit, exc, code):
    class Boom:
        async def run(self, question, ctx, use_web=True):
            raise exc
            yield  # pragma: no cover - makes this an async generator

    registry.override("orchestrator", Boom())
    r = client.post("/ask", json={"question": SECRET_QUESTION})
    assert r.status_code == 200
    events = _events(r.text)
    assert [k for k, _ in events] == ["error", "done"]
    assert events[0][1]["code"] == code
    assert SECRET_QUESTION not in r.text  # generic message, never the question
    assert len(audit.calls) == 1  # log_query still called once


def test_failure_after_answer_does_not_add_a_second_terminal_event(client):
    class LateBoom(FakeOrchestrator):
        async def run(self, question, ctx, use_web=True):
            async for e in super().run(question, ctx, use_web):
                yield e
            raise RuntimeError("late")

    registry.override("orchestrator", LateBoom())
    kinds = [
        k for k, _ in _events(client.post("/ask", json={"question": "Quel est le délai ?"}).text)
    ]
    assert kinds == ["thinking"] * 3 + ["answer", "done"]


def test_orchestrator_not_available_gives_error_event(client):
    registry.reset()  # no override, mode "real" is not simulated: force failure through a factory
    registry.override("audit", _SpyAudit())

    def broken():
        raise NotImplementedError

    class Missing:
        def run(self, *a, **k):
            return broken()

    registry.override("orchestrator", Missing())
    events = _events(client.post("/ask", json={"question": "Quel est le délai ?"}).text)
    assert [k for k, _ in events] == ["error", "done"]
