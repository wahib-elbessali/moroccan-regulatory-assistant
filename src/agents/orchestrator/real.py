# src/agents/orchestrator/real.py

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from src.agents.orchestrator.graph import GRAPH, GraphState
from src.core.config import cfg
from src.core.contracts.errors import AppError
from src.core.contracts.lang import detect_language
from src.core.contracts.models import Answer, ProcessEvent, UserContext
from src.core.contracts.registry import get_narrator

logger = logging.getLogger(__name__)

END_OF_GRAPH = object()

# Fixed, generic sentences (never the question, a passage or a title), by error code and language.
GENERIC: dict[str, dict[str, str]] = {
    "service_error": {
        "ar": "حدث خطأ أثناء معالجة الطلب.",
        "fr": "Une erreur est survenue lors du traitement.",
    },
    "invalid_input": {
        "ar": "الطلب غير صالح.",
        "fr": "La demande n'est pas valide.",
    },
}


def generic_message(code: str, language: str) -> str:
    table = GENERIC.get(code, GENERIC["service_error"])
    return table.get(language, table["fr"])


class RequestCancelled(Exception):
    """Raised inside the graph thread, at its next event, once the request has timed out."""


def _request_timeout_s() -> float:
    return float(cfg.agents.request_timeout_s)


def _recursion_limit(max_sub_questions: int, max_iterations: int) -> int:
    """Worst case: per sub-question, max_iterations x (search + grade + reformulate) + next_sub."""
    return max_sub_questions * (3 * max_iterations + 1) + 10


async def safe_narrate(event: ProcessEvent, language: str) -> AsyncIterator[str]:
    """Narration of one event. A failure skips that event and logs a warning (P3-26)."""
    try:
        narrator = get_narrator()
        async for text in narrator.narrate(event, language):
            yield text
    except Exception as exc:
        # Only the step and the exception type: the message could contain text.
        logger.warning("narration skipped: step=%s error=%s", event.step, type(exc).__name__)


class RealOrchestrator:
    async def run(
        self, question: str, ctx: UserContext, use_web: bool = True
    ) -> AsyncIterator[dict]:
        language = detect_language(question)
        events_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        cancelled = threading.Event()

        def emit(e: object) -> None:
            # Called from the graph thread. After a timeout it stops the graph at its next event.
            if cancelled.is_set():
                raise RequestCancelled()
            loop.call_soon_threadsafe(events_queue.put_nowait, e)

        initial_state: GraphState = {
            "question": question,
            "ctx": ctx,
            "use_web": use_web,
            "language": language,
            "sub_questions": [],
            "needs_web": False,
            "current_index": 0,
            "query": "",
            "tried": [],
            "iteration": 1,
            "passages": {},
            "unanswered": 0,
            "tokens": 0,
            "web_results": [],
            "answer": None,
            "emit": emit,
        }

        limit = _recursion_limit(int(cfg.agents.max_sub_questions), int(cfg.agents.max_iterations))

        def invoke_graph() -> dict[str, Any]:
            return GRAPH.invoke(initial_state, {"recursion_limit": limit})

        # Run graph in a separate thread
        task = asyncio.create_task(asyncio.to_thread(invoke_graph))

        def on_done(t: "asyncio.Task[dict[str, Any]]") -> None:
            if not t.cancelled():
                t.exception()  # mark it as retrieved (it is read below, or ignored after a timeout)
            events_queue.put_nowait(END_OF_GRAPH)

        task.add_done_callback(on_done)

        deadline = loop.time() + _request_timeout_s()

        # Yield thinking events while graph is running
        while True:
            try:
                item = await asyncio.wait_for(
                    events_queue.get(), timeout=max(deadline - loop.time(), 0.0)
                )
            except TimeoutError:
                cancelled.set()
                logger.error("orchestrator timed out")
                yield {
                    "event": "error",
                    "data": {
                        "code": "service_error",
                        "message": generic_message("service_error", language),
                    },
                }
                return

            if item is END_OF_GRAPH:
                break

            if isinstance(item, ProcessEvent):
                async for text in safe_narrate(item, language):
                    yield {"event": "thinking", "data": {"text": text}}
                yield {"event": "thinking", "data": {"text": "\n"}}

        try:
            res_state = task.result()
            answer: Answer = res_state["answer"]
            yield {"event": "answer", "data": answer.model_dump(mode="json")}
        except AppError as e:
            logger.error("orchestrator failed: %s", type(e).__name__)
            yield {
                "event": "error",
                "data": {"code": e.code, "message": generic_message(e.code, language)},
            }
        except Exception as e:
            logger.error("orchestrator failed: %s", type(e).__name__)
            yield {
                "event": "error",
                "data": {
                    "code": "service_error",
                    "message": generic_message("service_error", language),
                },
            }
