"""POST /ask: streams the Orchestrator's events as SSE, then `done` (P3-28 to P3-31).

The question is validated before the stream opens (P3-29). `audited_stream` (P5) adds `done`
and writes the audit log once. Neither the events nor the logs ever contain the question.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.audit import audited_stream
from src.core.config import cfg
from src.core.contracts.errors import AppError, InvalidInput
from src.core.contracts.models import UserContext
from src.core.contracts.registry import get_orchestrator
from src.core.security import get_current_user_context
from src.ingestion import normalize_ar

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_MAX_QUESTION_CHARS = 1000  # value of agents.max_question_chars in config.yaml
GENERIC_ERROR_MESSAGE = "The request could not be completed."


class AskRequest(BaseModel):
    question: str
    use_web: bool = True


def _max_question_chars() -> int:
    """agents.max_question_chars once `cfg.agents` exists (P5's config.py), else the YAML default."""
    agents = getattr(cfg, "agents", None)
    return int(getattr(agents, "max_question_chars", DEFAULT_MAX_QUESTION_CHARS))


def _validate_question(question: str) -> None:
    """Raise InvalidInput for an empty question (also empty after normalize_ar) or a too long one."""
    if not question.strip() or not normalize_ar(question).strip():
        raise InvalidInput("question must not be empty")
    if len(question) > _max_question_chars():
        raise InvalidInput("question is too long")


async def _safe_events(
    question: str, ctx: UserContext, use_web: bool
) -> AsyncIterator[dict[str, Any]]:
    """Events of `run`; any exception becomes one generic `error` event (P3-31)."""
    terminal_sent = False
    try:
        async for event in get_orchestrator().run(question, ctx, use_web):
            if event.get("event") in ("answer", "error"):
                terminal_sent = True
            yield event
    except Exception as exc:  # noqa: BLE001 - the stream must always end with done
        code = exc.code if isinstance(exc, AppError) else "service_error"
        # Log the exception type only: its message could contain the question or a passage.
        logger.error("orchestrator failed: %s", type(exc).__name__)
        if not terminal_sent:
            yield {"event": "error", "data": {"code": code, "message": GENERIC_ERROR_MESSAGE}}


def _to_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event["data"], ensure_ascii=False)
    return f"event: {event['event']}\ndata: {data}\n\n"


@router.post("")
@router.post("/")
async def ask_question(
    body: AskRequest,
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> StreamingResponse:
    _validate_question(body.question)

    async def stream() -> AsyncIterator[str]:
        events = _safe_events(body.question, ctx, body.use_web)
        async for event in audited_stream(ctx, body.question, events):
            yield _to_sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
