"""Tests of the isolated LangGraph experiment (two nodes, one conditional edge)."""

import pytest
from langgraph_experiment import build_graph


@pytest.mark.parametrize(
    "question,language",
    [("Quel est le délai ?", "fr"), ("ما هو أجل الطعن؟", "ar")],
)
def test_valid_question_goes_through_both_nodes(question, language):
    result = build_graph().invoke({"question": question})
    assert result["language"] == language
    assert result["answered"] is True


def test_blank_question_stops_after_first_node():
    result = build_graph().invoke({"question": "   "})
    assert result["language"] == "ar"  # classify ran
    assert "answered" not in result  # respond did not
