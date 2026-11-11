from collections.abc import AsyncIterator
from uuid import uuid4

from src.core.contracts.enums import AuditAction
from src.core.contracts.models import UserContext
from src.core.contracts.protocols import Audit


async def audited_stream(
    stream: AsyncIterator[str],
    audit_service: Audit,
    ctx: UserContext,
    doc_id: str | None = None,
    action: AuditAction = AuditAction.READ,
) -> AsyncIterator[str]:
    """Wraps an LLM token stream, collects the full text, and logs an audit record upon completion."""
    collected_tokens: list[str] = []
    try:
        async for chunk in stream:
            collected_tokens.append(chunk)
            yield chunk
    finally:
        full_text = "".join(collected_tokens)
        audit_service.log(
            user_id=ctx.user_id,
            action=action,
            doc_id=doc_id,
            details={"length": len(full_text), "status": "completed"},
            request_id=ctx.request_id or uuid4(),
        )