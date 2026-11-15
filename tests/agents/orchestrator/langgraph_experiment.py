"""Isolated LangGraph experiment for P3: two nodes and one conditional edge.

Not used by the product code. It checks, before the real graph is written (P3 spec §6.3), that
LangGraph is installed and behaves as expected: a node writes into the shared state, and a
conditional edge decides whether the run goes on or stops. The question is never logged.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.core.contracts.lang import detect_language


class ExperimentState(TypedDict, total=False):
    question: str
    language: str
    answered: bool


def classify(state: ExperimentState) -> ExperimentState:
    """Node 1: detect the language of the question (00-shared §4b)."""
    return {"language": detect_language(state["question"])}


def respond(state: ExperimentState) -> ExperimentState:
    """Node 2: reached only when the question has some content."""
    return {"answered": True}


def route_after_classify(state: ExperimentState) -> str:
    """Conditional edge: stop right away on a blank question, else go to `respond`."""
    return "respond" if state["question"].strip() else END


def build_graph():
    graph = StateGraph(ExperimentState)
    graph.add_node("classify", classify)
    graph.add_node("respond", respond)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_after_classify, {"respond": "respond", END: END})
    graph.add_edge("respond", END)
    return graph.compile()
