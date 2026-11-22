from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_current_user_context
from src.core.contracts.errors import NotFound
from src.core.contracts.models import (
    ConversationDetail,
    ConversationResponse,
    MessageIn,
    MessageResponse,
    UserContext,
)
from src.core.db.models import Conversation, ConversationMessage
from src.core.db.session import get_db

router = APIRouter()


class CreateConversationIn(BaseModel):
    title: str | None = None


def _get_owned_conversation(
    db: Session,
    conversation_id: UUID,
    ctx: UserContext,
) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or UUID(str(conv.user_id)) != ctx.user_id:
        raise NotFound("conversation not found")
    return conv


def _to_response(conv: Conversation) -> ConversationResponse:
    created_at = conv.created_at if isinstance(conv.created_at, datetime) else datetime.now(UTC)
    updated_at = conv.updated_at if isinstance(conv.updated_at, datetime) else created_at
    return ConversationResponse(
        conversation_id=UUID(str(conv.id)),
        title=str(conv.title) if conv.title is not None else None,
        created_at=created_at,
        updated_at=updated_at,
    )


def _to_message(row: ConversationMessage) -> MessageResponse:
    created_at = row.created_at if isinstance(row.created_at, datetime) else datetime.now(UTC)
    raw_answer = row.answer
    answer_obj = raw_answer if isinstance(raw_answer, dict) else {}
    lang = str(answer_obj.get("language") or "ar")
    return MessageResponse(
        position=int(row.position),
        question=str(row.question),
        available=True,
        answer=raw_answer,
        language=lang,
        created_at=created_at,
    )

@router.get("", response_model=list[ConversationResponse])
@router.get("/", response_model=list[ConversationResponse])
def list_conversations(
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> list[ConversationResponse]:
    """List conversations owned by the current user."""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == ctx.user_id)
        .order_by(Conversation.updated_at.desc())
    )
    rows = list(db.scalars(stmt).all())
    return [_to_response(c) for c in rows]


@router.post("", response_model=ConversationResponse, status_code=201)
@router.post("/", response_model=ConversationResponse, status_code=201)
def create_conversation(
    body: CreateConversationIn,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> ConversationResponse:
    """Create a new conversation for the current user."""
    now = datetime.now(UTC)
    title = body.title.strip() if body.title and body.title.strip() else None
    conv = Conversation(
        user_id=ctx.user_id,
        title=title,
        created_at=now,
        updated_at=now,
    )
    db.add(conv)
    db.flush()
    conv_id = UUID(str(conv.id))
    db.commit()
    persisted = db.scalars(select(Conversation).where(Conversation.id == conv_id)).one()
    return _to_response(persisted)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> ConversationDetail:
    """Retrieve a conversation with all persisted messages in order (P5-45)."""
    conv = _get_owned_conversation(db, conversation_id, ctx)
    ordered_rows = sorted(conv.messages, key=lambda m: int(m.position))
    created_at = conv.created_at if isinstance(conv.created_at, datetime) else datetime.now(UTC)
    updated_at = conv.updated_at if isinstance(conv.updated_at, datetime) else created_at
    return ConversationDetail(
        conversation_id=UUID(str(conv.id)),
        title=str(conv.title) if conv.title is not None else None,
        created_at=created_at,
        updated_at=updated_at,
        messages=[_to_message(row) for row in ordered_rows],
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
def append_message(
    conversation_id: UUID,
    body: MessageIn,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> MessageResponse:
    """Append a question/answer turn to an owned conversation (P5-45)."""
    conv = _get_owned_conversation(db, conversation_id, ctx)
    next_position = len(conv.messages) + 1
    now = datetime.now(UTC)

    answer_payload = (
        body.answer.model_dump(mode="json")
        if hasattr(body.answer, "model_dump")
        else body.answer
    )

    row = ConversationMessage(
        conversation_id=conv.id,
        position=next_position,
        question=body.question,
        answer=answer_payload,
        created_at=now,
    )
    db.add(row)

    if conv.title is None and body.question.strip():
        clean_q = body.question.strip()
        conv.title = clean_q[:60]
    conv.updated_at = now

    db.flush()
    db.commit()
    persisted_row = db.scalars(
        select(ConversationMessage).where(ConversationMessage.id == row.id)
    ).one()
    return _to_message(persisted_row)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),  # noqa: B008
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> None:
    """Delete a conversation owned by the current user."""
    conv = _get_owned_conversation(db, conversation_id, ctx)
    db.delete(conv)
    db.commit()
