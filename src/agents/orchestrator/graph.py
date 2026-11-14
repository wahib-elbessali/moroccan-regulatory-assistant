# src/agents/orchestrator/graph.py

import json
from pathlib import Path
from typing import Any, TypedDict

import yaml
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from src.agents.orchestrator.prompts import (
    GRADE_PROMPT,
    PLAN_PROMPT,
    REFORMULATE_PROMPT,
)
from src.core.config import cfg
from src.core.contracts.models import Answer, Passage, ProcessEvent, UserContext
from src.core.contracts.registry import (
    get_llm,
    get_retrieval,
    get_web_agent,
    get_writer,
)
from src.ingestion.normalize import normalize_ar  # P1 helper


class AgentsSettings(BaseModel):
    max_iterations: int = 3
    max_sub_questions: int = 3
    max_tokens_per_request: int = 8000
    grade_top_n: int = 5
    min_relevant: int = 1
    max_passages_to_writer: int = 8
    max_question_chars: int = 1000
    request_timeout_s: int = 60
    confidence_unknown_below: float = 0.4


def _load_agents_settings() -> AgentsSettings:
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if "agents" in data and isinstance(data["agents"], dict):
                return AgentsSettings(**data["agents"])
    return AgentsSettings()


agents_cfg = _load_agents_settings()


class GraphState(TypedDict, total=False):
    question: str
    ctx: UserContext
    use_web: bool
    language: str
    sub_questions: list[str]
    needs_web: bool
    current_index: int
    query: str
    tried: list[str]
    iteration: int
    last_passages: list[Passage]
    passages: dict[str, Passage]
    is_ok: bool
    unanswered: int
    stop_sub: bool
    tokens: int
    web_results: list[Any]
    answer: Answer | None
    emit: Any


def over_budget(state: GraphState) -> bool:
    return state["tokens"] >= agents_cfg.max_tokens_per_request


def parse_json_or_none(text: str) -> dict | None:
    try:
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        return json.loads(clean.strip())
    except Exception:
        return None


# --- Nodes ---


def plan_node(state: GraphState) -> dict:
    prompt = PLAN_PROMPT.format(
        max_sub_questions=agents_cfg.max_sub_questions, question=state["question"]
    )
    llm = get_llm()
    tokens = 0
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], max_tokens=300)
        tokens = llm.count_tokens(prompt + reply)
        data = parse_json_or_none(reply)
    except Exception:
        data = None

    subs = []
    if data and isinstance(data.get("sub_questions"), list):
        subs = [q for q in data["sub_questions"] if normalize_ar(q)]

    if not subs:
        subs = [state["question"]]

    sub_questions = subs[: agents_cfg.max_sub_questions]
    needs_web = bool(data.get("needs_web", False)) if data else False

    state["emit"](ProcessEvent(step="plan", data={"sub_questions": sub_questions}))

    first_q = sub_questions[0]
    return {
        "sub_questions": sub_questions,
        "needs_web": needs_web,
        "current_index": 0,
        "query": first_q,
        "tried": [first_q],
        "iteration": 1,
        "stop_sub": False,
        "tokens": state["tokens"] + tokens,
    }


def search_node(state: GraphState) -> dict:
    retrieval = get_retrieval()
    passages = retrieval.search(state["query"], state["ctx"], top_k=cfg.retrieval.top_k_final)

    titles = list(dict.fromkeys(p.chunk.title for p in passages))
    state["emit"](
        ProcessEvent(
            step="search",
            data={"query": state["query"], "count": len(passages), "titles": titles},
        )
    )
    return {"last_passages": passages}


def grade_node(state: GraphState) -> dict:
    last_passages = state.get("last_passages", [])
    top = last_passages[: agents_cfg.grade_top_n]

    if not top or over_budget(state):
        relevant = []
        tokens = 0
    else:
        doc_blocks = [
            f'<document n="{i + 1}">{p.chunk.text}</document>' for i, p in enumerate(top)
        ]
        prompt = GRADE_PROMPT.format(
            sub_question=state["sub_questions"][state["current_index"]],
            documents_text="\n".join(doc_blocks),
        )
        llm = get_llm()
        try:
            reply = llm.chat([{"role": "user", "content": prompt}], max_tokens=100)
            tokens = llm.count_tokens(prompt + reply)
            data = parse_json_or_none(reply)
        except Exception:
            tokens = 0
            data = None

        rel_indexes = data.get("relevant", []) if data else []
        relevant = [
            top[i - 1] for i in rel_indexes if isinstance(i, int) and 1 <= i <= len(top)
        ]

    current_passages = dict(state["passages"])
    for p in relevant:
        cid = p.chunk.chunk_id
        if cid not in current_passages or p.score > current_passages[cid].score:
            current_passages[cid] = p

    is_ok = len(relevant) >= agents_cfg.min_relevant
    kept_labels = list(
        dict.fromkeys(f"{p.chunk.title} — {p.chunk.article or ''}" for p in relevant)
    )

    state["emit"](
        ProcessEvent(
            step="grade",
            data={"relevant": len(relevant), "total": len(top), "kept": kept_labels},
        )
    )

    unanswered = state["unanswered"]
    if not is_ok and (over_budget(state) or state["iteration"] >= agents_cfg.max_iterations):
        unanswered += 1

    return {
        "passages": current_passages,
        "is_ok": is_ok,
        "unanswered": unanswered,
        "tokens": state["tokens"] + tokens,
    }


def after_grade_edge(state: GraphState) -> str:
    if over_budget(state):
        return "web"
    if state.get("is_ok") or state["iteration"] >= agents_cfg.max_iterations:
        if state["current_index"] + 1 < len(state["sub_questions"]):
            return "next_sub"
        return "web"
    return "reformulate"


def next_sub_node(state: GraphState) -> dict:
    next_idx = state["current_index"] + 1
    next_q = state["sub_questions"][next_idx]
    return {
        "current_index": next_idx,
        "query": next_q,
        "tried": [next_q],
        "iteration": 1,
        "stop_sub": False,
    }


def reformulate_node(state: GraphState) -> dict:
    sub_q = state["sub_questions"][state["current_index"]]
    tried_str = "\n".join(state["tried"])
    prompt = REFORMULATE_PROMPT.format(sub_question=sub_q, tried=tried_str)

    llm = get_llm()
    tokens = 0
    try:
        new_q = llm.chat([{"role": "user", "content": prompt}], max_tokens=60).strip()
        tokens = llm.count_tokens(prompt + new_q)
    except Exception:
        new_q = ""

    normalized_new = normalize_ar(new_q)
    if not normalized_new or new_q in state["tried"]:
        if state["current_index"] + 1 < len(state["sub_questions"]):
            next_idx = state["current_index"] + 1
            next_q = state["sub_questions"][next_idx]
            return {
                "current_index": next_idx,
                "query": next_q,
                "tried": [next_q],
                "iteration": 1,
                "stop_sub": False,
                "unanswered": state["unanswered"] + 1,
                "tokens": state["tokens"] + tokens,
            }
        return {
            "stop_sub": True,
            "unanswered": state["unanswered"] + 1,
            "tokens": state["tokens"] + tokens,
        }
    next_iter = state["iteration"] + 1
    state["emit"](
        ProcessEvent(
            step="reformulate",
            data={"old_query": state["query"], "new_query": new_q, "iteration": next_iter},
        )
    )

    return {
        "query": new_q,
        "tried": state["tried"] + [new_q],
        "iteration": next_iter,
        "stop_sub": False,
        "tokens": state["tokens"] + tokens,
    }


def after_reformulate_edge(state: GraphState) -> str:
    if state.get("stop_sub"):
        return "web"
    return "search"


def web_node(state: GraphState) -> dict:
    results = []

    if state["needs_web"] or state["unanswered"] > 0:
        web_agent = get_web_agent()
        lookup_res = web_agent.lookup(
            state["question"], state["ctx"], state["language"], state["use_web"]
        )
        results = lookup_res.results
        by_user = (not state["use_web"]) and state["ctx"].web_enabled and cfg.web.enabled

        state["emit"](
            ProcessEvent(
                step="web",
                data={"status": lookup_res.status, "count": len(results), "by_user": by_user},
            )
        )

    return {"web_results": results}


def write_node(state: GraphState) -> dict:
    state["emit"](ProcessEvent(step="write", data={}))
    best_passages = sorted(
        state["passages"].values(), key=lambda p: p.score, reverse=True
    )[: agents_cfg.max_passages_to_writer]

    writer = get_writer()
    answer = writer.write(
        state["question"],
        best_passages,
        state["web_results"],
        state["ctx"],
        emit=state["emit"],
    )
    return {"answer": answer}


# --- Graph Assembly ---
builder = StateGraph(GraphState)

builder.add_node("plan", plan_node)
builder.add_node("search", search_node)
builder.add_node("grade", grade_node)
builder.add_node("next_sub", next_sub_node)
builder.add_node("reformulate", reformulate_node)
builder.add_node("web", web_node)
builder.add_node("write", write_node)

builder.set_entry_point("plan")
builder.add_edge("plan", "search")
builder.add_edge("search", "grade")

builder.add_conditional_edges(
    "grade",
    after_grade_edge,
    {
        "next_sub": "next_sub",
        "reformulate": "reformulate",
        "web": "web",
    },
)

builder.add_edge("next_sub", "search")
builder.add_conditional_edges(
    "reformulate",
    after_reformulate_edge,
    {
        "search": "search",
        "web": "web",
    },
)
builder.add_edge("web", "write")
builder.add_edge("write", END)

GRAPH = builder.compile()