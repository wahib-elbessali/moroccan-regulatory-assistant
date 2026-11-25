# src/agents/orchestrator/validation.py
"""Strict readers of what the LLM returns to the orchestrator (P3, spec section 7).

`json.loads` only proves that a text is JSON. These helpers check the type and fall back to the
safe value of the spec's error table instead of raising. `graph.py` calls both of them:

- `parse_json_or_none`: the JSON object of a planner reply (the only JSON parser of the graph);
- `coerce_bool`: the planner's `needs_web` as a real boolean (a decision that sends the user's
  question to the web, so "false" must never count as True).

The other reads stay in `graph.py` (`_sub_question_text`, `grade_indexes`), which accept more
small-model formats than a stricter helper could: no second version of them lives here.

They never see a user, a passage or a role: access control stays in P2 (Qdrant and BM25 filters).
"""

from __future__ import annotations

import json
from typing import Any

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0", ""}


def parse_json_or_none(text: Any) -> dict | None:
    """The JSON object in an LLM reply (code fences tolerated), or None.

    None for an empty reply, a non-string, invalid JSON, or valid JSON that is not an object
    (a list, a number, a string, null).
    """
    if not isinstance(text, str):
        return None
    clean = text.strip()
    if not clean:
        return None
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    try:
        data = json.loads(clean.strip())
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def coerce_bool(value: Any, default: bool = False) -> bool:
    """A real boolean from what an LLM wrote.

    `bool("false")` is True in Python, which is the bug this function exists to prevent: the
    strings "true"/"false" (any case) and the integers 0/1 are understood, anything else gives
    `default`.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value in (0, 1) and bool(value)
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
    return default
