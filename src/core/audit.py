import time
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from src.core.contracts.protocols import Audit
from src.core.security import UserContext


async def audited_stream(
    generator: AsyncIterator[str],
    audit: Audit,
    ctx: UserContext,
    query: str,
) -> AsyncIterator[str]:
    """Wraps an LLM token stream to measure latency and audit upon completion."""
    start_time = time.perf_counter()
    request_id: UUID = ctx.request_id or uuid4()

    try:
        async for chunk in generator:
            yield chunk
    finally:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        audit.log_query(
            request_id=request_id,
            user_id=ctx.user_id,
            query=query,
            latency_ms=latency_ms,
        )
