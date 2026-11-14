# src/agents/orchestrator/graph.py

import json
import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

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

logger = logging.getLogger(__name__)


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
    return state["tokens"] >= cfg.agents.max_tokens_per_request


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
    t0 = time.perf_counter()
    prompt = PLAN_PROMPT.format(
        max_sub_questions=cfg.agents.max_sub_questions, question=state["question"]
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

    sub_questions = subs[: cfg.agents.max_sub_questions]
    needs_web = bool(data.get("needs_web", False)) if data else False

    state["emit"](ProcessEvent(step="plan", data={"sub_questions": sub_questions}))

    first_q = sub_questions[0]
    total_tokens = state["tokens"] + tokens
    logger.info(
        "orchestrator.plan",
        extra={
            "node": "plan",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "sub_questions": len(sub_questions),
            "tokens": total_tokens,
        },
    )
    return {
        "sub_questions": sub_questions,
        "needs_web": needs_web,
        "current_index": 0,
        "query": first_q,
        "tried": [first_q],
        "iteration": 1,
        "stop_sub": False,
        "tokens": total_tokens,
    }


def search_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    retrieval = get_retrieval()
    passages = retrieval.search(state["query"], state["ctx"], top_k=cfg.retrieval.top_k_final)

    titles = list(dict.fromkeys(p.chunk.title for p in passages))
    state["emit"](
        ProcessEvent(
            step="search",
            data={"query": state["query"], "count": len(passages), "titles": titles},
        )
    )
    logger.info(
        "orchestrator.search",
        extra={
            "node": "search",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "passages": len(passages),
            "tokens": state["tokens"],
        },
    )
    return {"last_passages": passages}


def grade_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    last_passages = state.get("last_passages", [])
    top = last_passages[: cfg.agents.grade_top_n]

    if not top or over_budget(state):
        relevant = []
        tokens = 0
    else:
        doc_blocks = [f'<document n="{i + 1}">{p.chunk.text}</document>' for i, p in enumerate(top)]
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
        relevant = [top[i - 1] for i in rel_indexes if isinstance(i, int) and 1 <= i <= len(top)]

    current_passages = dict(state["passages"])
    for p in relevant:
        cid = p.chunk.chunk_id
        if cid not in current_passages or p.score > current_passages[cid].score:
            current_passages[cid] = p

    is_ok = len(relevant) >= cfg.agents.min_relevant
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
    if not is_ok and (over_budget(state) or state["iteration"] >= cfg.agents.max_iterations):
        unanswered += 1

    total_tokens = state["tokens"] + tokens
    logger.info(
        "orchestrator.grade",
        extra={
            "node": "grade",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "passages": len(top),
            "relevant": len(relevant),
            "tokens": total_tokens,
        },
    )
    return {
        "passages": current_passages,
        "is_ok": is_ok,
        "unanswered": unanswered,
        "tokens": total_tokens,
    }


def after_grade_edge(state: GraphState) -> str:
    if over_budget(state):
        return "web"
    if state.get("is_ok") or state["iteration"] >= cfg.agents.max_iterations:
        if state["current_index"] + 1 < len(state["sub_questions"]):
            return "next_sub"
        return "web"
    return "reformulate"


def next_sub_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    next_idx = state["current_index"] + 1
    next_q = state["sub_questions"][next_idx]
    logger.info(
        "orchestrator.next_sub",
        extra={
            "node": "next_sub",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "sub_questions": len(state["sub_questions"]),
            "tokens": state["tokens"],
        },
    )
    return {
        "current_index": next_idx,
        "query": next_q,
        "tried": [next_q],
        "iteration": 1,
        "stop_sub": False,
    }


def reformulate_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
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

    total_tokens = state["tokens"] + tokens
    normalized_new = normalize_ar(new_q)
    if not normalized_new or new_q in state["tried"]:
        logger.info(
            "orchestrator.reformulate",
            extra={
                "node": "reformulate",
                "request_id": str(state["ctx"].request_id),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tokens": total_tokens,
            },
        )
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
                "tokens": total_tokens,
            }
        return {
            "stop_sub": True,
            "unanswered": state["unanswered"] + 1,
            "tokens": total_tokens,
        }

    next_iter = state["iteration"] + 1
    state["emit"](
        ProcessEvent(
            step="reformulate",
            data={"old_query": state["query"], "new_query": new_q, "iteration": next_iter},
        )
    )
    logger.info(
        "orchestrator.reformulate",
        extra={
            "node": "reformulate",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "tokens": total_tokens,
        },
    )
    return {
        "query": new_q,
        "tried": state["tried"] + [new_q],
        "iteration": next_iter,
        "stop_sub": False,
        "tokens": total_tokens,
    }


def after_reformulate_edge(state: GraphState) -> str:
    if state.get("stop_sub"):
        return "web"
    return "search"


def web_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
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

    logger.info(
        "orchestrator.web",
        extra={
            "node": "web",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "passages": len(results),
            "tokens": state["tokens"],
        },
    )
    return {"web_results": results}


def write_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    state["emit"](ProcessEvent(step="write", data={}))
    best_passages = sorted(state["passages"].values(), key=lambda p: p.score, reverse=True)[
        : cfg.agents.max_passages_to_writer
    ]

    writer = get_writer()
    answer = writer.write(
        state["question"],
        best_passages,
        state["web_results"],
        state["ctx"],
        emit=state["emit"],
    )
    logger.info(
        "orchestrator.write",
        extra={
            "node": "write",
            "request_id": str(state["ctx"].request_id),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "passages": len(best_passages),
            "tokens": state["tokens"],
        },
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
