# src/agents/orchestrator/real.py

import asyncio
from collections.abc import AsyncIterator

from src.core.contracts.errors import AppError
from src.core.contracts.lang import detect_language
from src.core.contracts.models import Answer, ProcessEvent, UserContext
from src.core.contracts.registry import get_narrator
from src.agents.orchestrator.graph import GRAPH

END_OF_GRAPH = object()


async def safe_narrate(event: ProcessEvent, language: str) -> AsyncIterator[str]:
    try:
        narrator = get_narrator()
        async for text in narrator.narrate(event, language):
            yield text
    except Exception:
        pass


class RealOrchestrator:

    async def run(
        self, question: str, ctx: UserContext, use_web: bool = True
    ) -> AsyncIterator[dict]:
        language = detect_language(question)
        events_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(e: ProcessEvent) -> None:
            loop.call_soon_threadsafe(events_queue.put_nowait, e)

        initial_state = {
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

        # Run graph in a separate thread
        task = asyncio.create_task(
            asyncio.to_thread(GRAPH.invoke, initial_state)
        )
        task.add_done_callback(lambda t: emit(END_OF_GRAPH))

        # Yield thinking events while graph is running
        while True:
            item = await events_queue.get()
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
            yield {"event": "error", "data": {"code": e.code, "message": e.message}}
        except Exception:
            yield {
                "event": "error",
                "data": {
                    "code": "service_error",
                    "message": "An internal service error occurred.",
                },
            }