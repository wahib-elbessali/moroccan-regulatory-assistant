# src/agents/orchestrator/graph.py

import json
import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.orchestrator.prompts import (
    grade_messages,
    plan_messages,
    reformulate_messages,
)
from src.agents.orchestrator.reformulation_guard import (
    complete_sub_questions,
    has_foreign_script,
    is_french,
    keeps_meaning,
    merge_needless_split,
)
from src.agents.orchestrator.validation import coerce_bool, parse_json_or_none
from src.core.config import cfg
from src.core.contracts.models import Answer, Passage, ProcessEvent, UserContext
from src.core.contracts.registry import (
    get_llm,
    get_retrieval,
    get_web_agent,
    get_writer,
)
from src.ingestion import normalize_ar  # P1 helper

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


def messages_text(messages: list[dict[str, str]]) -> str:
    """All the text sent to the LLM, to count its tokens (P3-15)."""
    return "\n".join(m["content"] for m in messages)


def count_tokens_safe(llm: Any, text: str) -> int:
    """Tokens of `text` (P3-15). Never raises.

    The real client counts with the Qwen tokenizer, which raises ServiceError when its files are
    missing (`make models` not run). That must not throw away a reply the LLM already gave, so we
    fall back to a rough estimate (about 3 characters per token) and log a warning (type only).
    """
    try:
        return int(llm.count_tokens(text))
    except Exception as exc:
        logger.warning("token count estimated: error=%s", type(exc).__name__)
        return len(text) // 3 + 1


def grade_indexes(reply: str) -> list[int]:
    """The passage numbers a grader reply keeps, tolerant of small-model formats.

    Accepts {"relevant": [1, 2]} (asked), a bare list [1, 2] and numbers written as strings
    (["1"], as qwen2.5:7b does). Anything else gives an empty list (nothing kept).
    """
    try:
        clean = reply.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        data = json.loads(clean.strip())
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("relevant", [])
    if not isinstance(data, list):
        return []
    found: list[int] = []
    for item in data:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            found.append(item)
        elif isinstance(item, str) and item.strip().isdigit():
            found.append(int(item.strip()))
    return found


# --- Nodes ---


def _sub_question_text(item: Any) -> str | None:
    """A planner sub-question as a string.

    Small models sometimes answer {"text": "..."} instead of a plain string; accept that too.
    Anything else is dropped.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "question", "query", "sub_question"):
            if isinstance(item.get(key), str):
                return item[key]
    return None


def plan_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    messages = plan_messages(state["question"], cfg.agents.max_sub_questions)
    llm = get_llm()
    tokens = 0
    try:
        reply = llm.chat(messages, max_tokens=300)
        tokens = count_tokens_safe(llm, messages_text(messages) + reply)
        data = parse_json_or_none(reply)
    except Exception:
        data = None

    subs = []
    if data and isinstance(data.get("sub_questions"), list):
        subs = [q for q in map(_sub_question_text, data["sub_questions"]) if q and normalize_ar(q)]
        subs = [q for q in subs if not has_foreign_script(q)]

    if not subs:
        subs = [state["question"]]

    sub_questions = merge_needless_split(state["question"], subs)[: cfg.agents.max_sub_questions]
    # A part of the question the planner dropped is added back (organizer feedback).
    sub_questions = complete_sub_questions(
        state["question"], sub_questions, cfg.agents.max_sub_questions
    )
    needs_web = coerce_bool(data.get("needs_web"), default=False) if data else False

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


def merge_passages(first: list[Passage], second: list[Passage]) -> list[Passage]:
    """Alternate two result lists, without duplicates (same chunk -> keep the higher score).

    Alternating, not sorting by score: both lists then reach the grader's top results.
    """
    merged: dict[str, Passage] = {}
    for i in range(max(len(first), len(second))):
        for results in (first, second):
            if i < len(results):
                p = results[i]
                cid = p.chunk.chunk_id
                if cid not in merged or p.score > merged[cid].score:
                    merged[cid] = p
    return list(merged.values())


def search_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    retrieval = get_retrieval()
    passages = retrieval.search(state["query"], state["ctx"], top_k=cfg.retrieval.top_k_final)
    # A French question can be badly translated by the planner, so its first search also runs
    # the question as typed. Same ctx: P2 applies the same access filter.
    question = state["question"]
    first_search = state["current_index"] == 0 and state["iteration"] == 1
    if first_search and is_french(question) and state["query"] != question:
        original = retrieval.search(question, state["ctx"], top_k=cfg.retrieval.top_k_final)
        passages = merge_passages(original, passages)

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
        graded = state["sub_questions"][state["current_index"]]
        # The grader also sees a French question as typed: a wrong translation must not make
        # it reject the passages found with the original question.
        if is_french(state["question"]) and graded != state["question"]:
            graded = f"{state['question']}\n{graded}"
        messages = grade_messages(
            graded,
            [p.chunk.text for p in top],
        )
        llm = get_llm()
        try:
            reply = llm.chat(messages, max_tokens=100)
            tokens = count_tokens_safe(llm, messages_text(messages) + reply)
            rel_indexes = grade_indexes(reply)
        except Exception:
            tokens = 0
            rel_indexes = []

        relevant = [top[i - 1] for i in dict.fromkeys(rel_indexes) if 1 <= i <= len(top)]

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

    total_tokens = state["tokens"] + tokens
    # The budget is checked on the total AFTER this call: a grading call that crosses the
    # budget with nothing relevant still leaves this sub-question unanswered (P3-18).
    budget_hit = total_tokens >= cfg.agents.max_tokens_per_request
    unanswered = state["unanswered"]
    if not is_ok and (budget_hit or state["iteration"] >= cfg.agents.max_iterations):
        unanswered += 1

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


_PROMPT_TAG = re.compile(r"</?\s*(query|question|tried|document)\b[^>]*>", re.IGNORECASE)


def clean_query(text: str) -> str:
    """The reformulated query alone: small models echo our tags, quotes or an extra line."""
    text = _PROMPT_TAG.sub("", text).strip()
    first_line = text.splitlines()[0] if text else ""
    return first_line.strip().strip("\"'«»“”").strip()


def reformulate_node(state: GraphState) -> dict:
    t0 = time.perf_counter()
    sub_q = state["sub_questions"][state["current_index"]]
    messages = reformulate_messages(sub_q, state["tried"])

    llm = get_llm()
    tokens = 0
    try:
        new_q = clean_query(llm.chat(messages, max_tokens=60))
        tokens = count_tokens_safe(llm, messages_text(messages) + new_q)
    except Exception:
        new_q = ""

    if has_foreign_script(new_q):
        new_q = ""
    total_tokens = state["tokens"] + tokens
    normalized_new = normalize_ar(new_q)
    # A reformulation that drops a legal term or a part of the question is rejected like a
    # duplicate: the loop for this sub-question ends (organizer feedback, P3 prompt fix).
    if new_q and not keeps_meaning(sub_q, new_q):
        logger.info("orchestrator.reformulate_rejected", extra={"node": "reformulate"})
        new_q = ""
        normalized_new = ""
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
        # Only the user's ORIGINAL question goes to the web, never a reformulation (P3-19).
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
