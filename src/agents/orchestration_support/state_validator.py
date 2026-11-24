# src/agents/orchestration_support/state_validator.py
"""Invariants of the orchestrator's `GraphState` (src/agents/orchestrator/graph.py).

`GraphState` is a local TypedDict of P3 and is not changed here. These functions only READ a
state (or a node's update) and report what is wrong, as a list of `StateIssue`. They never raise
(except `assert_valid_state`), never modify the state, and never put a question, a query or a
passage text in an issue (P3-33): `detail` holds codes and numbers only.

Not about access control: roles are filtered by P2 before any passage exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.agents.orchestration_support.orchestration_errors import OrchestrationStateError
from src.core.config import cfg
from src.core.contracts.models import Answer, Passage, UserContext

LANGUAGES = frozenset({"ar", "fr"})  # detect_language (00-shared §4b)

# Keys of `GraphState`. A test compares this set with `GraphState.__annotations__`, so a key
# added to the graph later is noticed instead of silently accepted or rejected.
STATE_KEYS = frozenset(
    {
        "question",
        "ctx",
        "use_web",
        "language",
        "sub_questions",
        "needs_web",
        "current_index",
        "query",
        "tried",
        "iteration",
        "last_passages",
        "passages",
        "is_ok",
        "unanswered",
        "stop_sub",
        "tokens",
        "web_results",
        "answer",
        "emit",
    }
)

# Set by `RealOrchestrator.run` before the graph starts.
INITIAL_KEYS = frozenset(
    {
        "question",
        "ctx",
        "use_web",
        "language",
        "sub_questions",
        "needs_web",
        "current_index",
        "query",
        "tried",
        "iteration",
        "passages",
        "unanswered",
        "tokens",
        "web_results",
        "answer",
        "emit",
    }
)


@dataclass(frozen=True)
class StateIssue:
    """One broken invariant. `code` is stable (tests and logs); `detail` has no user text."""

    code: str
    key: str
    detail: str = ""

    def as_pair(self) -> tuple[str, str]:
        return (self.code, self.key)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_types(state: Mapping[str, Any], issues: list[StateIssue]) -> None:
    def bad(key: str, expected: str) -> None:
        issues.append(StateIssue("wrong_type", key, f"expected {expected}"))

    checks: dict[str, tuple[Any, str]] = {
        "question": (lambda v: isinstance(v, str), "str"),
        "ctx": (lambda v: isinstance(v, UserContext), "UserContext"),
        "use_web": (lambda v: isinstance(v, bool), "bool"),
        "language": (lambda v: isinstance(v, str), "str"),
        "sub_questions": (
            lambda v: isinstance(v, list) and all(isinstance(q, str) for q in v),
            "list[str]",
        ),
        "needs_web": (lambda v: isinstance(v, bool), "bool"),
        "current_index": (_is_int, "int"),
        "query": (lambda v: isinstance(v, str), "str"),
        "tried": (
            lambda v: isinstance(v, list) and all(isinstance(q, str) for q in v),
            "list[str]",
        ),
        "iteration": (_is_int, "int"),
        "last_passages": (
            lambda v: isinstance(v, list) and all(isinstance(p, Passage) for p in v),
            "list[Passage]",
        ),
        "passages": (
            lambda v: isinstance(v, dict)
            and all(isinstance(k, str) and isinstance(p, Passage) for k, p in v.items()),
            "dict[str, Passage]",
        ),
        "is_ok": (lambda v: isinstance(v, bool), "bool"),
        "unanswered": (_is_int, "int"),
        "stop_sub": (lambda v: isinstance(v, bool), "bool"),
        "tokens": (_is_int, "int"),
        "web_results": (lambda v: isinstance(v, list), "list"),
        "answer": (lambda v: v is None or isinstance(v, Answer), "Answer | None"),
        "emit": (callable, "callable"),
    }
    for key, (test, expected) in checks.items():
        if key in state and not test(state[key]):
            bad(key, expected)


def _check_values(state: Mapping[str, Any], issues: list[StateIssue]) -> None:
    """Ranges and relations, only on the keys whose type is already right."""
    bad_types = {i.key for i in issues if i.code == "wrong_type"}

    def usable(*keys: str) -> bool:
        return all(k in state and k not in bad_types for k in keys)

    max_subs = int(cfg.agents.max_sub_questions)
    max_iters = int(cfg.agents.max_iterations)

    if usable("question") and not state["question"].strip():
        issues.append(StateIssue("empty_value", "question"))
    if usable("language") and state["language"] not in LANGUAGES:
        issues.append(StateIssue("unknown_language", "language", f"got {state['language']!r}"))
    if usable("sub_questions"):
        if len(state["sub_questions"]) > max_subs:
            issues.append(
                StateIssue(
                    "over_limit", "sub_questions", f"{len(state['sub_questions'])} > {max_subs}"
                )
            )
        if any(not q.strip() for q in state["sub_questions"]):
            issues.append(StateIssue("empty_value", "sub_questions", "blank sub-question"))
    if usable("current_index"):
        subs = state.get("sub_questions") if usable("sub_questions") else None
        high = max(len(subs) - 1, 0) if subs is not None else None
        if state["current_index"] < 0 or (high is not None and state["current_index"] > high):
            issues.append(
                StateIssue("out_of_range", "current_index", f"{state['current_index']} not in 0..")
            )
    if usable("iteration") and not 1 <= state["iteration"] <= max_iters:
        issues.append(
            StateIssue("out_of_range", "iteration", f"{state['iteration']} not in 1..{max_iters}")
        )
    if usable("tried"):
        if len(state["tried"]) > max_iters:
            issues.append(StateIssue("over_limit", "tried", f"{len(state['tried'])} > {max_iters}"))
        if len(set(state["tried"])) != len(state["tried"]):
            issues.append(StateIssue("duplicate_query", "tried"))
        if usable("iteration") and len(state["tried"]) > state["iteration"]:
            issues.append(StateIssue("inconsistent", "tried", "more queries than iterations"))
    if usable("query", "tried") and state["tried"] and state["query"] != state["tried"][-1]:
        issues.append(StateIssue("inconsistent", "query", "query is not the last tried"))
    if usable("tokens") and state["tokens"] < 0:
        issues.append(StateIssue("out_of_range", "tokens", "negative"))
    if usable("unanswered"):
        if state["unanswered"] < 0:
            issues.append(StateIssue("out_of_range", "unanswered", "negative"))
        elif usable("sub_questions") and state["unanswered"] > len(state["sub_questions"]):
            issues.append(StateIssue("out_of_range", "unanswered", "more than sub-questions"))
    if usable("passages"):
        for chunk_id, passage in state["passages"].items():
            if passage.chunk.chunk_id != chunk_id:
                issues.append(StateIssue("inconsistent", "passages", "key is not the chunk_id"))
                break


def validate_state(state: Mapping[str, Any], *, initial: bool = False) -> list[StateIssue]:
    """Every broken invariant of `state`; [] means valid.

    `initial=True` also requires the keys `RealOrchestrator.run` sets before the graph starts.
    """
    issues: list[StateIssue] = []
    for key in sorted(set(state) - STATE_KEYS):
        issues.append(StateIssue("unknown_key", key))
    if initial:
        for key in sorted(INITIAL_KEYS - set(state)):
            issues.append(StateIssue("missing_key", key))
    _check_types(state, issues)
    _check_values(state, issues)
    return issues


def validate_update(state: Mapping[str, Any], update: Mapping[str, Any]) -> list[StateIssue]:
    """Issues of the state a node would produce: `state` merged with the node's `update`.

    Also checks what a single step must never do: lower `tokens`, or add a key the state does
    not have. Use it around a node in a test; the graph itself is not touched.
    """
    issues: list[StateIssue] = []
    for key in sorted(set(update) - STATE_KEYS):
        issues.append(StateIssue("unknown_key", key))
    before, after = state.get("tokens"), update.get("tokens")
    if isinstance(before, int) and isinstance(after, int) and after < before:
        issues.append(StateIssue("tokens_decreased", "tokens", f"{before} -> {after}"))
    merged = {**state, **update}
    issues.extend(i for i in validate_state(merged) if i.code != "unknown_key")
    return issues


def assert_valid_state(state: Mapping[str, Any], *, initial: bool = False) -> None:
    """Raise `OrchestrationStateError` (codes only) if `validate_state` finds an issue."""
    issues = validate_state(state, initial=initial)
    if issues:
        raise OrchestrationStateError([i.as_pair() for i in issues])
