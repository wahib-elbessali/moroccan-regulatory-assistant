# tests/agents/orchestrator/test_state_validator.py
"""Tests of src/agents/orchestration_support/state_validator.py (new, independent of the graph).

The graph itself is only READ: `GRAPH.stream(..., stream_mode="values")` gives the state after
each step, and every one of them must satisfy the invariants.
"""

from uuid import uuid4

import pytest
from test_orchestrator_graph import (
    ScriptedLLM,
    StubRetrieval,
    StubWebAgent,
    StubWriter,
    _make_chunk,
)

from src.agents.orchestration_support.orchestration_errors import OrchestrationStateError
from src.agents.orchestration_support.state_validator import (
    INITIAL_KEYS,
    STATE_KEYS,
    assert_valid_state,
    validate_state,
    validate_update,
)
from src.agents.orchestrator.graph import GRAPH, GraphState
from src.core.config import cfg
from src.core.contracts import registry
from src.core.contracts.models import Passage, UserContext


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    registry.reset()


@pytest.fixture
def ctx() -> UserContext:
    return UserContext(
        user_id=uuid4(), username="meryem", role="lecteur", web_enabled=True, request_id=uuid4()
    )


def initial_state(ctx: UserContext, question: str = "سؤال") -> dict:
    """The state `RealOrchestrator.run` builds before the graph starts."""
    return {
        "question": question,
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


def codes(issues) -> set[tuple[str, str]]:
    return {i.as_pair() for i in issues}


# --- Compatibility with the existing GraphState -----------------------------------------------
def test_state_keys_equal_the_graph_state_keys():
    # If the graph gains or loses a key, this fails and the validator must follow.
    assert set(GraphState.__annotations__) == set(STATE_KEYS)


def test_initial_keys_are_state_keys():
    assert INITIAL_KEYS <= STATE_KEYS


def test_initial_state_of_real_orchestrator_is_valid(ctx):
    assert validate_state(initial_state(ctx), initial=True) == []


# --- Detection ---------------------------------------------------------------------------------
def test_unknown_and_missing_keys(ctx):
    state = initial_state(ctx)
    state["surprise"] = 1
    del state["tokens"]
    found = codes(validate_state(state, initial=True))
    assert ("unknown_key", "surprise") in found
    assert ("missing_key", "tokens") in found
    # a missing key is only reported for an initial state
    assert ("missing_key", "tokens") not in codes(validate_state(state))


@pytest.mark.parametrize(
    "key,value",
    [
        ("question", 5),
        ("ctx", {"user": 1}),
        ("use_web", "true"),
        ("sub_questions", "a"),
        ("sub_questions", ["a", 2]),
        ("needs_web", "false"),
        ("current_index", 1.5),
        ("current_index", True),
        ("tried", None),
        ("iteration", "1"),
        ("passages", []),
        ("unanswered", None),
        ("tokens", "10"),
        ("answer", "text"),
        ("emit", "not callable"),
    ],
)
def test_wrong_types(ctx, key, value):
    state = initial_state(ctx)
    state[key] = value
    assert ("wrong_type", key) in codes(validate_state(state))


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"question": "   "}, ("empty_value", "question")),
        ({"language": "en"}, ("unknown_language", "language")),
        ({"sub_questions": ["a", "b", "c", "d"]}, ("over_limit", "sub_questions")),
        ({"sub_questions": ["a", " "]}, ("empty_value", "sub_questions")),
        ({"sub_questions": ["a"], "current_index": 1}, ("out_of_range", "current_index")),
        ({"current_index": -1}, ("out_of_range", "current_index")),
        ({"iteration": 0}, ("out_of_range", "iteration")),
        ({"iteration": 99}, ("out_of_range", "iteration")),
        ({"tried": ["a", "a"], "query": "a", "iteration": 2}, ("duplicate_query", "tried")),
        ({"tried": ["a", "b"], "query": "b", "iteration": 1}, ("inconsistent", "tried")),
        ({"tried": ["a"], "query": "z"}, ("inconsistent", "query")),
        ({"tokens": -1}, ("out_of_range", "tokens")),
        ({"unanswered": -1}, ("out_of_range", "unanswered")),
        ({"sub_questions": ["a"], "unanswered": 2}, ("out_of_range", "unanswered")),
    ],
)
def test_value_checks(ctx, changes, expected):
    state = initial_state(ctx)
    state.update(changes)
    assert expected in codes(validate_state(state))


def test_passage_key_must_be_the_chunk_id(ctx):
    state = initial_state(ctx)
    passage = Passage(chunk=_make_chunk(), score=0.5, rank=1)
    state["passages"] = {"wrong-key": passage}
    assert ("inconsistent", "passages") in codes(validate_state(state))
    state["passages"] = {passage.chunk.chunk_id: passage}
    assert validate_state(state) == []


def test_a_wrong_type_does_not_crash_the_range_checks(ctx):
    state = initial_state(ctx)
    state.update({"tokens": "x", "iteration": None, "tried": 3, "sub_questions": None})
    assert validate_state(state)  # reported, not raised


# --- validate_update ---------------------------------------------------------------------------
def test_update_cannot_lower_tokens_or_add_keys(ctx):
    state = initial_state(ctx)
    state["tokens"] = 50
    found = codes(validate_update(state, {"tokens": 10, "mystery": 1}))
    assert ("tokens_decreased", "tokens") in found
    assert ("unknown_key", "mystery") in found


def test_update_is_checked_on_the_merged_state(ctx):
    state = initial_state(ctx)
    assert validate_update(state, {"tokens": 10}) == []
    assert ("wrong_type", "tokens") in codes(validate_update(state, {"tokens": "10"}))


# --- assert_valid_state ------------------------------------------------------------------------
def test_assert_valid_state_raises_codes_without_user_text(ctx):
    state = initial_state(ctx, question="SECRET_QUESTION_TEXT")
    state["tokens"] = -5
    with pytest.raises(OrchestrationStateError) as info:
        assert_valid_state(state)
    assert ("out_of_range", "tokens") in info.value.issues
    assert "SECRET_QUESTION_TEXT" not in str(info.value)


def test_assert_valid_state_silent_when_valid(ctx):
    assert_valid_state(initial_state(ctx), initial=True)


def test_the_validator_does_not_modify_the_state(ctx):
    state = initial_state(ctx)
    state["tokens"] = -1
    snapshot = dict(state)
    validate_state(state)
    validate_update(state, {"tokens": 3})
    assert state == snapshot


# --- Every real intermediate state of the existing graph --------------------------------------
def _run_and_validate(ctx, replies, *, passages=None, tokens_per_call=10, question="سؤال"):
    registry.override("llm", ScriptedLLM(replies, tokens_per_call=tokens_per_call))
    registry.override("retrieval", StubRetrieval(default=passages or []))
    registry.override("web_agent", StubWebAgent())
    registry.override("writer", StubWriter())
    state = initial_state(ctx, question)
    steps = 0
    previous_tokens = 0
    for values in GRAPH.stream(state, {"recursion_limit": 60}, stream_mode="values"):
        steps += 1
        assert validate_state(values) == [], f"step {steps}: {codes(validate_state(values))}"
        assert values["tokens"] >= previous_tokens
        previous_tokens = values["tokens"]
    assert steps > 1
    return values


def test_graph_states_stay_valid_when_everything_is_relevant(ctx):
    p = Passage(chunk=_make_chunk(), score=0.9, rank=1)
    final = _run_and_validate(
        ctx,
        [
            '{"sub_questions": ["a", "b"], "needs_web": false}',
            '{"relevant": [1]}',
            '{"relevant": [1]}',
        ],
        passages=[p],
    )
    assert final["answer"] is not None


def test_graph_states_stay_valid_when_nothing_is_relevant(ctx):
    p = Passage(chunk=_make_chunk(), score=0.9, rank=1)
    replies = ['{"sub_questions": ["a", "b", "c"], "needs_web": true}'] + [
        '{"relevant": []}',
        "a2",
        '{"relevant": []}',
        "a3",
        '{"relevant": []}',
    ] * 3
    final = _run_and_validate(ctx, replies, passages=[p])
    assert final["unanswered"] == 3


def test_graph_states_stay_valid_when_the_budget_is_reached(ctx):
    final = _run_and_validate(
        ctx,
        ['{"sub_questions": ["a", "b"], "needs_web": false}'],
        tokens_per_call=cfg.agents.max_tokens_per_request + 1,
    )
    assert final["tokens"] >= cfg.agents.max_tokens_per_request


def test_graph_states_stay_valid_for_a_bad_plan_and_a_duplicate_reformulation(ctx):
    p = Passage(chunk=_make_chunk(), score=0.9, rank=1)
    # plan not JSON -> the question itself; the reformulation repeats the query -> loop ends
    _run_and_validate(ctx, ["garbage", '{"relevant": []}', "سؤال"], passages=[p])
