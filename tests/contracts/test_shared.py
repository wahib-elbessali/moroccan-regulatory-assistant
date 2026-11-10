"""Checks of the shared definitions in src/core/contracts (00-shared §3–§7)."""

import uuid

import pytest
from pydantic import ValidationError

from src.core.contracts import (
    ALLOWED_TRANSITIONS,
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    Chunk,
    DocStatus,
    InvalidInput,
    LeakBlocked,
    detect_language,
    is_public,
    make_chunk_id,
    make_doc_id,
)


def _chunk(**overrides):
    doc_id = make_doc_id(b"file", None)
    data = dict(
        chunk_id=make_chunk_id(doc_id, 0),
        doc_id=doc_id,
        chunk_index=0,
        total_chunks=1,
        text="نص",
        text_normalized="نص",
        title="T",
        article=None,
        hierarchy=[],
        page_start=1,
        page_end=1,
        language="ar",
        source_file="a.pdf",
        source=None,
        date=None,
        allowed_roles=[],
        owner_id=None,
    )
    data.update(overrides)
    return Chunk(**data)


def test_doc_id_depends_on_scope():
    owner = uuid.uuid4()
    assert make_doc_id(b"same", None) != make_doc_id(b"same", owner)
    assert len(make_doc_id(b"same", None)) == 64


def test_chunk_id_is_stable():
    assert make_chunk_id("abc", 3) == make_chunk_id("abc", 3)
    assert make_chunk_id("abc", 3) != make_chunk_id("abc", 4)


def test_chunk_validation():
    _chunk()
    with pytest.raises(ValidationError):
        _chunk(chunk_index=1)
    with pytest.raises(ValidationError):
        _chunk(page_start=3, page_end=2)


def test_status_transitions():
    assert DocStatus.READY in ALLOWED_TRANSITIONS[DocStatus.INDEXED]
    assert DocStatus.READY not in ALLOWED_TRANSITIONS[DocStatus.RECEIVED]
    assert DocStatus.FAILED not in ALLOWED_TRANSITIONS[DocStatus.READY]
    assert DocStatus.EXTRACTING in ALLOWED_TRANSITIONS[DocStatus.FAILED]


def test_document_roles():
    assert is_public(PUBLIC_ROLES)
    assert not is_public(INTERNAL_ROLES)
    assert not is_public([])


@pytest.mark.parametrize(
    "text, expected",
    [("ما هو أجل الطعن؟", "ar"), ("Quel est le délai ?", "fr"), ("شنو هو الأجل؟", "ar")],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_errors():
    assert InvalidInput("x").http_status == 422
    assert LeakBlocked("x", hits=3).hits == 3


def test_conversation_message_hides_answer_when_unavailable():
    from datetime import UTC, datetime

    from src.core.contracts import Answer, ConversationDetail, MessageIn, MessageResponse

    answer = Answer(status="unknown", text="نص", citations=[], confidence=0.0, language="ar")
    MessageIn(question="سؤال", answer=answer)
    now = datetime.now(UTC)
    hidden = MessageResponse(
        position=1, question="سؤال", available=False, answer=None, language="ar", created_at=now
    )
    detail = ConversationDetail(
        conversation_id=uuid.uuid4(), title=None, created_at=now, updated_at=now, messages=[hidden]
    )
    assert detail.messages[0].answer is None
