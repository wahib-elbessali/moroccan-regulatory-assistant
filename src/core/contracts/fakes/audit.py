"""
src/core/contracts/fakes/audit.py
In-memory fake implementation of AuditProtocol (P5 contract).
Used for logging verification in cross-part tests without database writes.
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


class FakeAudit:
    """In-memory fake implementation of AuditProtocol."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []

    def log_action(
        self,
        user_id: UUID | None,
        action_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.actions.append(
            {
                "user_id": user_id,
                "action_type": action_type,
                "details": details or {},
                "timestamp": datetime.now(timezone.utc),
            }
        )

    def log_query(
        self,
        request_id: UUID,
        user_id: UUID | None,
        query: str,
        latency_ms: int,
    ) -> None:
        self.queries.append(
            {
                "request_id": request_id,
                "user_id": user_id,
                "query": query,
                "latency_ms": latency_ms,
                "timestamp": datetime.now(timezone.utc),
            }
        )