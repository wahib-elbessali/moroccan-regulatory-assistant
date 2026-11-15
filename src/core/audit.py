import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from src.core.contracts.enums import AuditAction
from src.core.contracts.models import UserContext
from src.core.contracts.registry import get_audit
from src.core.db.models import AuditLog
from src.core.db.session import SessionLocal
from src.core.security import request_id_var

logger = logging.getLogger(__name__)


class RealAudit:
    """PostgreSQL-backed Audit implementation (P5-34, P5-36)."""

    def log_query(
        self,
        request_id: UUID,
        user_id: UUID,
        query: str,
        latency_ms: int,
    ) -> None:
        try:
            with SessionLocal() as session:
                entry = AuditLog(
                    request_id=request_id,
                    user_id=user_id,
                    action=AuditAction.QUERY_ASK.value,
                    query_text=query,
                    latency_ms=latency_ms,
                )
                session.add(entry)
                session.commit()
        except Exception:
            logger.exception("Failed to write query audit log to database")

    def log_action(
        self,
        user_id: UUID | None,
        action_type: str,
        details: dict[str, Any],
    ) -> None:
        req_id = request_id_var.get() or uuid4()
        try:
            with SessionLocal() as session:
                entry = AuditLog(
                    request_id=req_id,
                    user_id=user_id,
                    action=action_type,
                    details=details,
                )
                session.add(entry)
                session.commit()
        except Exception:
            logger.exception("Failed to write action audit log to database")


def real_audit() -> RealAudit:
    """Factory used by registry.py when contracts.audit == 'real'."""
    return RealAudit()


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
