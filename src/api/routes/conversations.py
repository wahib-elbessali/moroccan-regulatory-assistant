from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user_context, record_audit_event
from src.core.contracts.errors import Forbidden, NotFound
from src.core.contracts.models import UserContext
from src.core.db.models import Conversation
from src.core.db.session import get_db

router = APIRouter()


@router.get("")
@router.get("/")
def list_conversations(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> list[dict[str, Any]]:
    """List all conversations belonging to the authenticated user."""
    stmt = select(Conversation).where(Conversation.user_id == ctx.user_id)
    convs = db.scalars(stmt).all()
    return [
        {
            "id": str(c.id),
            "title": (str(c.title) if hasattr(c, "title") and c.title else "Conversation"),
            "created_at": (
                c.created_at.isoformat() if hasattr(c, "created_at") and c.created_at else None
            ),
        }
        for c in convs
    ]


@router.post("")
@router.post("/")
def create_conversation(
    body: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Create a new conversation for the user."""
    conv_id = uuid4()
    title = (body or {}).get("title", "New Conversation")
    conv = Conversation(
        id=conv_id,
        user_id=ctx.user_id,
        title=title,
    )
    db.add(conv)
    db.commit()
    return {"id": str(conv_id), "title": title}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Get details and messages of a specific conversation."""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise NotFound("conversation not found")
    if conv.user_id != ctx.user_id:
        raise Forbidden("access denied")

    return {
        "id": str(conv.id),
        "title": str(conv.title) if hasattr(conv, "title") else "Conversation",
        "messages": [],  # populated via chat/orchestrator if available
    }


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Delete a conversation owned by the user."""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise NotFound("conversation not found")
    if conv.user_id != ctx.user_id:
        raise Forbidden("access denied")

    db.delete(conv)
    db.commit()
    record_audit_event(ctx, "delete_conversation", {"conversation_id": str(conversation_id)})
    return {"id": str(conversation_id), "status": "deleted"}


@router.post("/{conversation_id}/messages")
def add_message(
    conversation_id: UUID,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Add a message to a conversation."""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise NotFound("conversation not found")
    if conv.user_id != ctx.user_id:
        raise Forbidden("access denied")

    content = body.get("content", "")
    return {
        "conversation_id": str(conversation_id),
        "status": "message_added",
        "content_length": len(content),
    }
