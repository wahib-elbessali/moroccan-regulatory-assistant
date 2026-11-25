# tests/agents/orchestrator/test_orchestrator_integration.py
"""validation.py and orchestration_support are really used by the orchestrator.

Every test here runs the real graph (stub LLM, retrieval, web agent and writer from
test_orchestrator_graph.py) and checks something that only happens if the integration works:

- `graph.py` calls `validation.parse_json_or_none` and `validation.coerce_bool`;
- `needs_web` written as "false" no longer sends the question to the web;
- the request timeout comes from `cfg.agents.request_timeout_s` and nowhere else;
- `RequestLimits` bounds what a worst-case run does;
- `state_validator` finds no broken invariant in any state the graph goes through.
"""

import json
import time
from uuid import uuid4

import pytest
from test_orchestrator_graph import (
    ScriptedLLM,
    StubRetrieval,
    StubWebAgent,
    StubWriter,
    _make_chunk,
)

from src.agents.orchestration_support.orchestration_limits import RequestLimits
from src.agents.orchestration_support.state_validator import validate_state, validate_update
from src.agents.orchestrator import graph as graph_module
from src.agents.orchestrator import real as real_module
from src.agents.orchestrator import validation
from src.agents.orchestrator.real import RealOrchestrator, _recursion_limit
from src.core.config import cfg
from src.core.contracts import registry
from src.core.contracts.models import Answer, Passage, UserContext

QUESTION = "سؤال عن القانون"
EMPTY_GRADE = '{"relevant": []}'
GOOD_GRADE = '{"relevant": [1]}'


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    registry.reset()


@pytest.fixture
def ctx() -> UserContext:
    return UserContext(
        user_id=uuid4(), username="meryem", role="lecteur", web_enabled=True, request_id=uuid4()
    )


def _plan(sub_questions: list, needs_web=False) -> str:
    return json.dumps({"sub_questions": sub_questions, "needs_web": needs_web})


def _passage() -> Passage:
    return Passage(chunk=_make_chunk(), score=0.9, rank=1)


def _install(llm: ScriptedLLM, *, found: bool = True):
    ret = StubRetrieval(default=[_passage()] if found else [])
    web = StubWebAgent()
    registry.override("llm", llm)
    registry.override("retrieval", ret)
    registry.override("web_agent", web)
    registry.override("writer", StubWriter())
    return ret, web


async def _run(ctx: UserContext) -> list[dict]:
    return [e async for e in RealOrchestrator().run(QUESTION, ctx, use_web=True)]


def _spy(monkeypatch, module, name: str) -> list[tuple]:
    original = getattr(module, name)
    calls: list[tuple] = []

    def wrapper(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


# --- validation.py is used by the graph ----------------------------------------------------------
def test_graph_has_no_second_json_parser():
    assert graph_module.parse_json_or_none is validation.parse_json_or_none
    assert graph_module.coerce_bool is validation.coerce_bool


@pytest.mark.asyncio
async def test_the_graph_runs_the_validation_helpers(ctx, monkeypatch):
    parse_calls = _spy(monkeypatch, graph_module, "parse_json_or_none")
    bool_calls = _spy(monkeypatch, graph_module, "coerce_bool")
    _install(ScriptedLLM([_plan(["q1"]), GOOD_GRADE]))

    events = await _run(ctx)

    assert events[-1]["event"] == "answer"
    assert len(parse_calls) == 1  # the planner reply (the grader has its own reader)
    assert len(bool_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_web", ["false", "False", " no ", "0", 0, "maybe", None, []])
async def test_needs_web_that_is_not_a_clear_yes_never_calls_the_web(ctx, needs_web):
    # bool("false") is True: before validation.coerce_bool was used, the user's question was sent
    # to the web although the planner had said no.
    _, web = _install(ScriptedLLM([_plan(["q1"], needs_web), GOOD_GRADE]))

    events = await _run(ctx)

    assert events[-1]["event"] == "answer"
    assert web.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_web", [True, "true", "True", "yes", 1])
async def test_needs_web_that_is_a_clear_yes_calls_the_web_with_the_original_question(
    ctx, needs_web
):
    _, web = _install(ScriptedLLM([_plan(["q1"], needs_web), GOOD_GRADE]))

    await _run(ctx)

    assert len(web.calls) == 1
    assert web.calls[0][0] == QUESTION  # never a sub-question or a reformulation (P3-19)


@pytest.mark.asyncio
async def test_an_unanswered_sub_question_still_falls_back_to_the_web(ctx):
    # The old rule is unchanged: needs_web false, but nothing relevant found -> web fallback.
    replies = [_plan(["q1"], False), EMPTY_GRADE, "q1 v2", EMPTY_GRADE, "q1 v3", EMPTY_GRADE]
    llm = ScriptedLLM(replies)
    _, web = _install(llm)

    events = await _run(ctx)

    assert events[-1]["event"] == "answer"
    assert len(web.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grade_reply",
    [
        '{"relevant": ["1"]}',
        "[1]",
        '["1"]',
        '```json\n{"relevant": [1]}\n```',
        '{"relevant": [1, 1]}',
    ],
)
async def test_grader_formats_that_mean_document_1_keep_it(ctx, grade_reply):
    # grade_indexes (kept in graph.py) replaces validation.clean_relevant: same coverage.
    llm = ScriptedLLM([_plan(["q1"]), grade_reply])
    ret, _ = _install(llm)

    events = await _run(ctx)

    assert events[-1]["event"] == "answer"
    assert llm.calls == 2  # plan + grade: the passage was kept, so no reformulation
    assert len(ret.queries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("grade_reply", ['{"relevant": [true, 1.5, 99, 0, -1]}', "not json", "{}"])
async def test_grader_replies_that_keep_nothing_start_a_reformulation(ctx, grade_reply):
    llm = ScriptedLLM([_plan(["q1"]), grade_reply, "q1 v2", GOOD_GRADE])
    ret, _ = _install(llm)

    await _run(ctx)

    assert llm.calls == 4  # plan, grade (nothing kept), reformulate, grade
    assert [q for q, _ in ret.queries] == ["q1", "q1 v2"]


# --- one source for the timeout --------------------------------------------------------------------
def test_request_timeout_is_read_from_the_config_only(monkeypatch):
    monkeypatch.setattr(cfg.agents, "request_timeout_s", 7)
    assert real_module._request_timeout_s() == 7.0
    assert not hasattr(real_module, "DEFAULT_REQUEST_TIMEOUT_S")


@pytest.mark.asyncio
async def test_the_configured_timeout_stops_a_slow_request(ctx, monkeypatch):
    class SlowLLM(ScriptedLLM):
        def chat(self, messages, **kwargs):
            time.sleep(0.5)
            return super().chat(messages, **kwargs)

    monkeypatch.setattr(cfg.agents, "request_timeout_s", 0.1)  # the real.py helper is not patched
    _install(SlowLLM([_plan(["q1"])]))

    events = await _run(ctx)

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "service_error"
    assert "answer" not in [e["event"] for e in events]


# --- RequestLimits bound a real run, and every state the graph builds is valid --------------------
def _initial_state(ctx: UserContext) -> dict:
    return {
        "question": QUESTION,
        "ctx": ctx,
        "use_web": True,
        "language": "ar",
        "sub_questions": [],
        "needs_web": False,
        "current_index": 0,
        "query": "",
        "tried": [],
        "iteration": 1,
        "passages": {},
        "unanswered": 0,
        "tokens": 0,
        "web_results": [],
        "answer": None,
        "emit": lambda event: None,
    }


def _snapshots(ctx: UserContext) -> list[dict]:
    """The full state after every node, as LangGraph reports it (stream_mode="values")."""
    limit = _recursion_limit(int(cfg.agents.max_sub_questions), int(cfg.agents.max_iterations))
    stream = graph_module.GRAPH.stream(
        _initial_state(ctx), {"recursion_limit": limit}, stream_mode="values"
    )
    return list(stream)


def _worst_case_replies() -> list[str]:
    subs, iters = int(cfg.agents.max_sub_questions), int(cfg.agents.max_iterations)
    replies = [_plan([f"q{i}" for i in range(subs)])]
    for s in range(subs):
        for it in range(iters):
            replies.append(EMPTY_GRADE)
            if it < iters - 1:
                replies.append(f"q{s}_v{it + 2}")
    return replies


SCENARIOS = {
    "answered_at_once": (lambda: ScriptedLLM([_plan(["q1"]), GOOD_GRADE]), True),
    "worst_case_nothing_relevant": (lambda: ScriptedLLM(_worst_case_replies()), True),
    "budget_crossed_by_the_first_grade": (
        lambda: ScriptedLLM([_plan(["q1", "q2"]), EMPTY_GRADE], tokens_per_call=4000),
        True,
    ),
    "llm_down_on_the_planner": (lambda: ScriptedLLM([GOOD_GRADE], fail_on_call=1), True),
    "reformulation_repeats_the_query": (
        lambda: ScriptedLLM([_plan(["q1"]), EMPTY_GRADE, "q1"]),
        True,
    ),
    "planner_gives_too_many_sub_questions": (
        lambda: ScriptedLLM([_plan(["a", "b", "c", "d", "e"])] + [GOOD_GRADE] * 5),
        True,
    ),
    "nothing_found_at_all": (lambda: ScriptedLLM([_plan(["q1"])]), False),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_state_of_a_real_run_is_valid_and_within_the_limits(name, ctx):
    make_llm, found = SCENARIOS[name]
    llm = make_llm()
    ret, _ = _install(llm, found=found)
    limits = RequestLimits.from_config()

    states = _snapshots(ctx)

    # state_validator ran on every state of the run (the first one is the input state).
    assert len(states) >= 5
    for previous, state in zip(states, states[1:], strict=False):
        assert validate_state(state, initial=True) == [], f"invalid state in {name}"
        assert validate_update(previous, state) == [], f"invalid step in {name}"
    # The limits are respected on every path.
    assert len(ret.queries) <= limits.worst_case_searches
    assert llm.calls <= limits.worst_case_llm_calls
    assert len(states[-1]["sub_questions"]) <= limits.max_sub_questions
    assert isinstance(states[-1]["answer"], Answer)


def test_worst_case_does_reach_the_computed_bound(ctx):
    ret, _ = _install(ScriptedLLM(_worst_case_replies()))

    states = _snapshots(ctx)

    assert len(ret.queries) == RequestLimits.from_config().worst_case_searches
    assert states[-1]["unanswered"] == int(cfg.agents.max_sub_questions)


def test_the_token_budget_stops_the_llm_calls(ctx):
    llm = ScriptedLLM([_plan(["q1", "q2"]), EMPTY_GRADE], tokens_per_call=4000)
    ret, _ = _install(llm)

    states = _snapshots(ctx)

    assert llm.calls == 2  # plan + one grade: the budget (8000) is then reached
    assert states[-1]["tokens"] >= int(cfg.agents.max_tokens_per_request)
    assert len(ret.queries) == 1  # the second sub-question is never searched
    assert states[-1]["unanswered"] == 1


def test_the_state_validator_is_not_vacuous(ctx):
    """It must really report a broken state, otherwise the tests above prove nothing."""
    _install(ScriptedLLM([_plan(["q1"]), GOOD_GRADE]))
    state = _snapshots(ctx)[-1]
    assert validate_state(state, initial=True) == []

    broken = {**state, "iteration": int(cfg.agents.max_iterations) + 1}
    assert validate_state(broken, initial=True) != []
    assert validate_update(state, {"tokens": state["tokens"] - 1}) != []
