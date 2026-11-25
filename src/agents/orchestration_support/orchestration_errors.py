# src/agents/orchestration_support/orchestration_errors.py
"""Errors of the P3 support tools.

They carry issue CODES only, never a question, a query or a passage text (P3-33).
"""

from __future__ import annotations

from collections.abc import Sequence


class OrchestrationStateError(Exception):
    """The orchestrator's state broke an invariant. `issues` are `(code, key)` pairs."""

    def __init__(self, issues: Sequence[tuple[str, str]]) -> None:
        self.issues: tuple[tuple[str, str], ...] = tuple(issues)
        summary = ", ".join(f"{code}:{key}" for code, key in self.issues) or "no issue"
        super().__init__(f"invalid orchestrator state ({summary})")
