# tests/agents/orchestrator/test_validation.py
"""Tests of src/agents/orchestrator/validation.py (strict readers of LLM replies).

`graph.py` calls `parse_json_or_none` and `coerce_bool` (see test_orchestrator_integration.py,
which proves it on a real graph run); the tests below pin their exact behaviour.
"""

import pytest

from src.agents.orchestrator.validation import coerce_bool, parse_json_or_none


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('  {"a": 1}  ', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ("{}", {}),
        ("", None),
        ("   ", None),
        ("garbage", None),
        ("{broken", None),
        ('["a"]', None),
        ("42", None),
        ('"text"', None),
        ("null", None),
        (None, None),
        (42, None),
        (b'{"a": 1}', None),
    ],
)
def test_parse_json_or_none(text, expected):
    assert parse_json_or_none(text) == expected


def test_parse_json_or_none_deeply_nested_does_not_raise():
    assert parse_json_or_none("[" * 100000) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("true", True),
        ("TRUE", True),
        (" yes ", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("no", False),
        ("0", False),
        ("", False),
        (1, True),
        (0, False),
        (2, False),
        (-1, False),
        ("maybe", False),
        (None, False),
        ([], False),
        (1.0, False),
    ],
)
def test_coerce_bool_default_false(value, expected):
    assert coerce_bool(value) is expected


def test_coerce_bool_string_false_is_not_true():
    """The reason this function exists: bool("false") is True."""
    assert bool("false") is True
    assert coerce_bool("false") is False


def test_coerce_bool_default_is_used_only_for_unreadable_strings_and_other_types():
    assert coerce_bool("maybe", default=True) is True
    assert coerce_bool(None, default=True) is True
    assert coerce_bool("false", default=True) is False
    assert coerce_bool("true", default=False) is True
