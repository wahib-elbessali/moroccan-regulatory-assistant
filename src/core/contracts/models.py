"""Data models that cross part boundaries (00-shared §5)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

# --- 5.1 UserContext (P5) -------------------------------------------------------------------


class UserContext(BaseModel):
    """Built by get_current_user_context on every request. Never built by another part,
    except in tests through the fixtures."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    username: str
    role: str  # a RoleName value
    web_enabled: bool  # roles.web_enabled of the user's role, read by P5 on every request
    request_id: UUID

    def has_role(self, required_role: str) -> bool:
        return self.role == required_role


# Document roles (document_roles, copied into each chunk's allowed_roles).
PUBLIC_ROLES: list[str] = ["lecteur", "editeur"]
INTERNAL_ROLES: list[str] = ["editeur"]
PRIVATE_ROLES: list[str] = []  # with owner_id set


def is_public(roles: list[str]) -> bool:
    return "lecteur" in roles


# --- 5.2 Chunk (P1 -> P2) ----------------------------------------------------------------------


class Chunk(BaseModel):
    chunk_id: str  # make_chunk_id(doc_id, chunk_index)
    doc_id: str
    chunk_index: int  # 0-based position in the document
    total_chunks: int  # number of chunks of this document; same value on all of them
    text: str  # as extracted, cleaned; shown and cited
    text_normalized: str  # P1 normalization; used by BM25
    title: str  # document title (DocumentMeta.title)
    article: str | None  # e.g. "المادة 12"; None if the text has no articles
    hierarchy: list[str]  # headings above the chunk, outermost first; [] if none
    page_start: int  # 1-based
    page_end: int
    language: str  # "ar" | "fr"
    source_file: str  # original file name (DocumentMeta.source_file)
    source: str | None  # where the document comes from (DocumentMeta.source)
    date: str | None  # the document's date as written by the uploader (DocumentMeta.date)
    allowed_roles: list[str]  # the document's roles (document_roles); empty until published
    owner_id: UUID | None  # set for private uploads

    @model_validator(mode="after")
    def _check_index(self) -> "Chunk":
        if not 0 <= self.chunk_index < self.total_chunks:
            raise ValueError("chunk_index must be in 0 … total_chunks - 1")
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        return self


# --- 5.2b DocumentMeta (P5 -> P1) --------------------------------------------------------------


class DocumentMeta(BaseModel):
    """What the uploader typed, passed to ingest and copied into every chunk."""

    title: str  # typed by the uploader
    source_file: str  # original file name as uploaded (stored file is <doc_id>.<ext>)
    source: str | None = None  # free text: a URL, "الجريدة الرسمية عدد 7250", …
    date: str | None = None  # free text, e.g. "2025-03-12"; None if not given


# --- 5.3 Passage (P2 -> P3, P4) ----------------------------------------------------------------


class Passage(BaseModel):
    chunk: Chunk
    score: float  # final score after re-ranking, higher is better
    rank: int  # 1-based, after re-ranking


# --- 5.4 WebResult (P6 -> P3, P4) --------------------------------------------------------------


class WebResult(BaseModel):
    url: str
    title: str
    snippet: str


class WebLookup(BaseModel):
    status: str  # "done" | "skipped" (skipped for ANY reason)
    results: list[WebResult]


# --- 5.5 Citation and Answer (P4 -> P3 -> P7) --------------------------------------------------


class Citation(BaseModel):
    doc_id: str | None  # None for a web source
    url: str | None  # set for a web source
    title: str
    article: str | None
    page: int | None
    source: str | None  # chunk.source for a corpus document, None for a web source
    date: str | None  # chunk.date for a corpus document, None for a web source
    excerpt: str  # exact text from the passage that backs the claim


class Answer(BaseModel):
    status: str  # an AnswerStatus value
    text: str  # in `language`; citation markers [1], [2]…
    citations: list[Citation]  # index i+1 matches marker [i+1]
    confidence: float  # 0.0–1.0
    language: str  # "ar" | "fr" (Arabic or Darija question -> "ar"; never Darija)


# --- 5.6 ProcessEvent (P3 -> P4 narrator) ------------------------------------------------------


class ProcessEvent(BaseModel):
    """`data` keys per step (process data only, never passage text):
    plan: sub_questions · search: query, count, titles · grade: relevant, total, kept ·
    reformulate: old_query, new_query, iteration · web: status, count, by_user ·
    write: — · verify: supported, total, reasons (reason codes only)."""

    step: str  # a StepType value
    data: dict


# --- 8. HTTP API models shared with P7 ---------------------------------------------------------


class UserCreate(BaseModel):
    username: str  # same rules as AccountRequestIn
    password: str
    full_name: str
    role_id: int


class UserResponse(BaseModel):
    user_id: UUID
    username: str
    full_name: str
    role: str  # a RoleName value
    is_active: bool
    created_at: datetime
    # never the password or its hash


class AccountRequestIn(BaseModel):
    username: str  # 3–32 characters: letters, digits, "." "_" "-"
    password: str  # at least auth.min_password_length characters (checked by P5)
    full_name: str  # 1–100 characters


class AccountRequestResponse(BaseModel):
    request_id: UUID
    username: str
    full_name: str
    status: str  # an AccountRequestStatus value
    created_at: datetime
    decided_by: UUID | None
    decided_at: datetime | None
    # never the password or its hash


class DocumentResponse(BaseModel):
    doc_id: str
    title: str
    source_file: str
    source: str | None
    date: str | None
    status: str  # a DocStatus value
    error: str | None
    roles: list[str]  # [] for a private upload
    is_mine: bool  # the user uploaded it as a private upload
    created_at: datetime


class MeResponse(BaseModel):
    user_id: UUID
    username: str
    role: str  # a RoleName value
    web_available: bool  # config web.enabled AND roles.web_enabled of the user's role


class RoleResponse(BaseModel):
    role_id: int
    name: str
    web_enabled: bool


class ConversationResponse(BaseModel):
    conversation_id: UUID
    title: str | None  # the first question, cut to 60 characters; None before it
    created_at: datetime
    updated_at: datetime  # time of the last exchange


class MessageIn(BaseModel):
    question: str  # as sent to /ask
    answer: Answer  # as received in the `answer` event (00-shared §5.7)


class MessageResponse(BaseModel):
    position: int  # 1, 2, 3… within the conversation
    question: str
    available: bool  # False: a cited document is no longer visible to the user
    answer: Answer | None  # None when available is False
    language: str  # answer.language, kept to show the "no longer available" notice
    created_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]  # by position
