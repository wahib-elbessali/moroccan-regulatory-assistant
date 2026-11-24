# src/agents/orchestration_support/orchestration_limits.py
"""The limits of one request as one object, and a check of the `agents` config at start-up.

`cfg.agents` (config.yaml) is the only source of the numbers; `graph.py` and `real.py` read it
directly. This module adds what they do not do: derive the worst cases (P3-16) and warn, once,
when the configuration is inconsistent. `real_orchestrator()` calls `audit_configured_limits()`.
It never raises: a wrong config must not stop a request that could have been answered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.config import cfg

logger = logging.getLogger(__name__)

# Codes returned by `check_limits`.
NOT_POSITIVE = "not_positive"
MIN_RELEVANT_ABOVE_GRADED = "min_relevant_above_graded"
GRADED_ABOVE_RETRIEVED = "graded_above_retrieved"
WRITER_BELOW_RELEVANT = "writer_below_min_relevant"


@dataclass(frozen=True)
class RequestLimits:
    """Limits of one `/ask` request (`config.yaml`, section `agents`)."""

    max_iterations: int
    max_sub_questions: int
    max_tokens: int
    grade_top_n: int
    min_relevant: int
    max_passages_to_writer: int
    request_timeout_s: float

    @classmethod
    def from_config(cls, agents: Any = None) -> RequestLimits:
        """Read the limits from `cfg.agents`, or from any object with the same attributes."""
        a = agents if agents is not None else cfg.agents
        return cls(
            max_iterations=int(a.max_iterations),
            max_sub_questions=int(a.max_sub_questions),
            max_tokens=int(a.max_tokens_per_request),
            grade_top_n=int(a.grade_top_n),
            min_relevant=int(a.min_relevant),
            max_passages_to_writer=int(a.max_passages_to_writer),
            request_timeout_s=float(a.request_timeout_s),
        )

    @property
    def worst_case_searches(self) -> int:
        """P3-16: max_sub_questions x max_iterations."""
        return self.max_sub_questions * self.max_iterations

    @property
    def worst_case_llm_calls(self) -> int:
        """1 plan + a grade per search + a reformulation between two searches of a sub-question."""
        reformulations = self.max_sub_questions * max(self.max_iterations - 1, 0)
        return 1 + self.worst_case_searches + reformulations


def check_limits(limits: RequestLimits, top_k_final: int | None = None) -> list[str]:
    """Problems of a configuration, as `code:name` strings; [] means consistent.

    `top_k_final` (`retrieval.top_k_final`) enables the check that grading does not ask for more
    passages than one search returns.
    """
    problems: list[str] = []
    values = {
        "max_iterations": limits.max_iterations,
        "max_sub_questions": limits.max_sub_questions,
        "max_tokens": limits.max_tokens,
        "grade_top_n": limits.grade_top_n,
        "min_relevant": limits.min_relevant,
        "max_passages_to_writer": limits.max_passages_to_writer,
        "request_timeout_s": limits.request_timeout_s,
    }
    problems.extend(f"{NOT_POSITIVE}:{name}" for name, v in values.items() if v <= 0)
    if limits.min_relevant > limits.grade_top_n:
        # a sub-question could never be answered
        problems.append(f"{MIN_RELEVANT_ABOVE_GRADED}:min_relevant")
    if top_k_final is not None and limits.grade_top_n > top_k_final:
        problems.append(f"{GRADED_ABOVE_RETRIEVED}:grade_top_n")
    if limits.max_passages_to_writer < limits.min_relevant:
        problems.append(f"{WRITER_BELOW_RELEVANT}:max_passages_to_writer")
    return problems


def audit_configured_limits() -> list[str]:
    """Check `cfg.agents` once and log the result (codes and numbers only, never any text).

    Returns the problems found. Never raises.
    """
    try:
        limits = RequestLimits.from_config()
        problems = check_limits(limits, int(cfg.retrieval.top_k_final))
        for problem in problems:
            logger.warning("orchestrator limits inconsistent: %s", problem)
        logger.info(
            "orchestrator limits: worst_case_searches=%d worst_case_llm_calls=%d timeout_s=%s",
            limits.worst_case_searches,
            limits.worst_case_llm_calls,
            limits.request_timeout_s,
        )
        return problems
    except Exception as exc:
        logger.warning("orchestrator limits not audited: error=%s", type(exc).__name__)
        return []
