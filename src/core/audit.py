import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from src.core.contracts.models import UserContext
from src.core.contracts.registry import get_audit

logger = logging.getLogger(__name__)


async def audited_stream(
    ctx: UserContext,
    question: str,
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Yields every event of `events`, then `done`, and calls `log_query` in `finally` (00-shared §6.1)."""
    start_time = time.perf_counter()
    latency_ms = 0

    try:
        async for event in events:
            yield event

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        yield {
            "event": "done",
            "data": {
                "request_id": str(ctx.request_id),
                "latency_ms": latency_ms,
            },
        }
    finally:
        if latency_ms == 0:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
        try:
            get_audit().log_query(
                request_id=ctx.request_id,
                user_id=ctx.user_id,
                query=question,
                latency_ms=latency_ms,
            )
        except Exception:
            logger.exception("Failed to write query audit log")
