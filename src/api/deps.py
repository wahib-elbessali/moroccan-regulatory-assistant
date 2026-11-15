"""FastAPI security and audit dependencies (00-shared §6.1, P5-21, P5-22)."""

from collections.abc import Callable
from typing import Any

from fastapi import Depends

from src.core.contracts.errors import Forbidden
from src.core.contracts.models import UserContext
from src.core.contracts.registry import get_audit
from src.core.security import get_current_user_context


def require_roles(allowed_roles: list[str]) -> Callable[[UserContext], UserContext]:
    """FastAPI dependency raising Forbidden if ctx.role is not in allowed_roles (P5-21)."""

    def _dependency(
        ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
    ) -> UserContext:
        if ctx.role not in allowed_roles:
            raise Forbidden("forbidden")
        return ctx

    return _dependency


def record_audit_event(
    context: UserContext,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Thin wrapper over Audit.log_action using the authenticated UserContext (P5-22)."""
    get_audit().log_action(context.user_id, action, details or {})


__all__ = [
    "get_current_user_context",
    "require_roles",
    "record_audit_event",
]
