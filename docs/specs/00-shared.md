# 00 — Shared definitions

> Status: **draft v0.1**.
> This file is the single source of truth for every name, ID, type, status, error and function signature used **between** parts. Part specs reference it and never redefine anything in it. The same definitions exist as code in `src/core/contracts/`; the two are changed together, in the same PR, approved by the parts that use them.

---

## 1. Conventions

- Python 3.11+, type hints everywhere, Pydantic v2 models for every object that crosses a part boundary.
- Contracts are `typing.Protocol` classes. CI runs `mypy` on `src/`, so an implementation that doesn't match its Protocol fails CI.
- Functions between parts are **synchronous**, except the streaming ones (`LLMClient.stream`, `Orchestrator.run`, `Narrator.narrate`), which are async generators.
- IDs are strings in JSON and in function signatures (`str`), except `user_id` and `request_id`, which are `UUID` as in the P5 schema (they become strings only in JSON and HTTP bodies).
- Timestamps are timezone-aware UTC (`datetime` with `tzinfo=UTC`), ISO 8601 in JSON.
- Text is UTF-8. Arabic text is stored as extracted (for display and citation) **and** normalized (for search); see `Chunk`.
- A function that fails raises one of the shared errors in §7. It never returns `None` or an error string to signal failure.

---

## 2. Glossary

| Term | Meaning | FR | AR |
|---|---|---|---|
| Document | One uploaded file and everything derived from it | document | وثيقة |
| Corpus | All documents added by editors | corpus | المتن |
| Private upload | A document uploaded by a user for their own use | document privé | وثيقة خاصة |
| Chunk | A piece of a document, normally one article, indexed for search | fragment | مقطع |
| Passage | A chunk returned by a search, with its scores | passage | فقرة مسترجعة |
| Article | The legal unit a chunk follows | article | مادة / فصل |
| Citation | Reference backing a claim: document, page, article, excerpt | citation | إحالة |
| Role | A row of the `roles` table | rôle | دور |
| Rights | The roles a document is visible to (`document_roles`) | droits | صلاحيات |
| Publish | Set a document's rights and make it searchable | publier | نشر |
| Hidden | Indexed but not searchable by anyone | masqué | مخفي |
| Fingerprint | HMAC of a 4-word sequence, stored by P6 to detect leaks | empreinte | بصمة |
| Thinking stream | Live narration of the process, before the answer | réflexion | سير التفكير |

---

## 3. Enumerations

```python
# src/core/contracts/enums.py
from enum import StrEnum


class RoleName(StrEnum):  # rows of the `roles` table
    ADMIN = "admin"  # accounts, roles, audit; sees no corpus content
    EDITEUR = "editeur"  # the jurist: manages the corpus, sees public + internal
    LECTEUR = "lecteur"  # the citizen: sees public + own uploads


class DocStatus(StrEnum):
    RECEIVED = "received"  # row created, file stored
    EXTRACTING = "extracting"  # P1 extracting / OCR
    CHUNKED = "chunked"  # P1 produced chunks
    INDEXED = "indexed"  # P2 indexed (hidden) + P6 registered
    READY = "ready"  # rights set, searchable
    FAILED = "failed"  # any step failed; document stays hidden


class AuditAction(StrEnum):  # values of audit_log.action
    LOGIN = "login"  # P5, success or not
    QUERY_ASK = "query_ask"  # P5 (log_query), end of every /ask
    ADMIN_UPDATE = "admin_update"  # P5: users, roles, document rights, account requests, web switch
    DOCUMENT_UPLOAD = "document_upload"  # P5, upload accepted
    DOCUMENT_DELETE = "document_delete"  # P5, document deleted
    INGEST_FAILED = "ingest_failed"  # P1, user_id None
    WEB_BLOCKED = "web_blocked"  # P6, query refused by the leak filter (never the query text)


class AccountRequestStatus(StrEnum):  # values of account_requests.status
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"  # answer with verified citations
    UNKNOWN = "unknown"  # nothing found in the documents this user may see
    # (whether the corpus lacks it or it is restricted: never told apart)


class StepType(StrEnum):  # process events, P3 → P4 narrator
    PLAN = "plan"
    SEARCH = "search"
    GRADE = "grade"
    REFORMULATE = "reformulate"
    WEB = "web"
    WRITE = "write"
    VERIFY = "verify"
```

Allowed status transitions (anything else raises `InvalidInput`):

```
received → extracting → chunked → indexed → ready
any status except ready and failed → failed
failed → extracting            (retry)
ready → indexed                (rights being changed: hidden again)
```

---

## 4. Identifiers

```python
# src/core/contracts/ids.py
import hashlib, uuid

CHUNK_NAMESPACE = uuid.UUID("6f1c2b0e-8a4d-4c1e-9b3a-2d5e7f9a1c30")  # never change


def make_doc_id(file_bytes: bytes, owner_id: uuid.UUID | None) -> str:
    """documents.id. owner_id is set for private uploads, None for corpus documents."""
    scope = str(owner_id) if owner_id else "corpus"
    return hashlib.sha256(scope.encode() + b"\x00" + file_bytes).hexdigest()


def make_file_hash(file_bytes: bytes) -> str:
    """documents.file_hash (kept for reference; the extraction cache is keyed by doc_id)."""
    return hashlib.sha256(file_bytes).hexdigest()


def make_content_hash(normalized_text: str) -> str:
    """Duplicate warning: documents.content_hash. Two files with the same text (e.g. a digital
    PDF and a scan of it) get the same content hash but different doc_ids."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def make_chunk_id(doc_id: str, chunk_index: int) -> str:
    """Qdrant point ID and BM25 key."""
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{doc_id}:{chunk_index}"))
```

- Every part uses these functions. Nobody computes an ID another way.
- `chunk_index` starts at 0 and follows the order of the document.
- A `doc_id` that already exists in `documents` means the same file was already uploaded in the same scope: the upload is rejected with `Conflict`. A `Conflict` can only happen within one scope, so it never reveals another user's document.

### 4b. Question language

```python
# src/core/contracts/lang.py — written by P3
def detect_language(text: str) -> str:
    """ "fr" if more than half of the letters are Latin, else "ar".
    Arabic and Darija written in Arabic script give "ar"."""
```

English, written in Latin letters, gives `"fr"`: an English question is answered in French, on purpose. P3 computes the question's language with it once per request; P4 uses the same function, so the answer, the narration and the web query agree on the language. P1 uses it for each chunk's `language`.

---

## 5. Data models

### 5.1 `UserContext` (P5)

```python
# src/core/contracts/models.py
from pydantic import BaseModel, ConfigDict
from uuid import UUID


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: UUID
    username: str
    role: str  # a RoleName value
    web_enabled: bool  # roles.web_enabled of the user's role, read by P5 on every request
    request_id: UUID

    def has_role(self, required_role: str) -> bool:
        return self.role == required_role
```

Built by `get_current_user_context` on every request. Never built by another part, except in tests through the fixture in §9.

Document roles (`document_roles`, copied into each chunk's `allowed_roles`):

| Document | Roles | Visible to |
|---|---|---|
| Public | `["lecteur", "editeur"]` | `lecteur`, `editeur` |
| Internal | `["editeur"]` | `editeur` |
| Private upload | `[]`, with `owner_id` set | its owner only |

`is_public(roles)` is `"lecteur" in roles`. `admin` is never in a document's roles. `contracts/models.py` provides the three lists as `PUBLIC_ROLES`, `INTERNAL_ROLES`, `PRIVATE_ROLES`, and the function `is_public`.

Roles must fit the document: a private upload (`owner_id` set) only ever has `[]`; a corpus document (`owner_id` null) only ever has the public or the internal list.

### 5.2 `Chunk` (P1 → P2)

```python
class Chunk(BaseModel):
    chunk_id: str  # make_chunk_id(doc_id, chunk_index)
    doc_id: str
    chunk_index: int  # 0-based position in the document
    total_chunks: int  # number of chunks of this document; same value on all of them
    text: str  # as extracted, cleaned; shown and cited
    text_normalized: str  # P1 normalization; used by BM25
    title: str  # document title (DocumentMeta.title)
    article: str | None  # e.g. "المادة 12"; None if the text has no articles
    hierarchy: list[str]  # headings above the chunk, outermost first,
    # e.g. ["الكتاب الأول", "الباب الثاني", "الفصل الثالث"]; [] if none
    page_start: int  # 1-based
    page_end: int
    language: str  # "ar" | "fr"
    source_file: str  # original file name (DocumentMeta.source_file)
    source: str | None  # where the document comes from (DocumentMeta.source)
    date: str | None  # the document's date as written by the uploader (DocumentMeta.date)
    allowed_roles: list[str]  # the document's roles (document_roles); empty until published
    owner_id: UUID | None  # set for private uploads
```

- `0 <= chunk_index < total_chunks` and `page_start <= page_end` for every chunk.
- `hierarchy` does not include `article`; the article is in its own field.

### 5.2b `DocumentMeta` (P5 → P1)

What the uploader typed, passed to `ingest` and copied into every chunk of the document.

```python
class DocumentMeta(BaseModel):
    title: str  # typed by the uploader
    source_file: (
        str  # original file name as uploaded (the stored file is renamed to <doc_id>.<ext>)
    )
    source: str | None = None  # free text: a URL, "الجريدة الرسمية عدد 7250", …; None if not given
    date: str | None = (
        None  # free text, e.g. "2025-03-12" or the Bulletin Officiel date; None if not given
    )
```

### 5.3 `Passage` (P2 → P3, P4)

```python
class Passage(BaseModel):
    chunk: Chunk
    score: float  # final score after re-ranking, higher is better
    rank: int  # 1-based, after re-ranking
```

### 5.4 `WebResult` (P6 → P3, P4)

```python
class WebResult(BaseModel):
    url: str
    title: str
    snippet: str


class WebLookup(BaseModel):
    status: str  # "done" | "skipped" (skipped for ANY reason: disabled, blocked, offline, error)
    results: list[WebResult]
```

### 5.5 `Citation` and `Answer` (P4 → P3 → P7)

```python
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
    language: str  # "ar" | "fr": "fr" for a French question, "ar" (standard Arabic)
    # for an Arabic or Darija question. Never Darija.
```

### 5.6 `ProcessEvent` (P3 → P4 narrator)

```python
class ProcessEvent(BaseModel):
    step: str  # a StepType value
    data: dict  # see the table below; process data only, never passage text
```

| `step` | `data` keys |
|---|---|
| `plan` | `sub_questions: list[str]` |
| `search` | `query: str`, `count: int`, `titles: list[str]` (titles the user may see) |
| `grade` | `relevant: int`, `total: int`, `kept: list[str]` ("title — article" of each relevant passage; the user may see them) |
| `reformulate` | `old_query: str`, `new_query: str`, `iteration: int` |
| `web` | `status: "done" \| "skipped"`, `count: int`, `by_user: bool` (true only when the user turned web search off for this question) |
| `write` | — |
| `verify` | `supported: int`, `total: int`, `reasons: list[str]` (reason codes only: `no_citation`, `not_supported`, `excerpt_not_found`) |

### 5.7 SSE events (`/ask` → P7)

Each event is one SSE message: `event: <type>` and `data: <JSON>`.

| `event` | `data` | When |
|---|---|---|
| `thinking` | `{"text": str}` | Narration fragments, any number, in order; a fragment `"\n"` ends each step's narration |
| `answer` | an `Answer` | Once, after the Juge has verified it |
| `error` | `{"code": str, "message": str}` | On failure, in place of `answer`; `done` follows and the stream ends |
| `done` | `{"request_id": str, "latency_ms": int}` | Always last |

---

## 6. Contracts between parts

Each Protocol below lives in `src/core/contracts/protocols.py`, its fake in `src/core/contracts/fakes/`, and is obtained through `get_<name>()` (§9). Errors refer to §7.

The streaming methods (`LLMClient.stream`, `Orchestrator.run`, `Narrator.narrate`) are declared `def … -> AsyncIterator[…]`; implementations write them as `async def` with `yield`.

### 6.1 Provided by P5

```python
class DocumentRights(Protocol):
    def set_document_roles(self, doc_id: str, roles: list[str]) -> dict:
        """hide → document_roles → P2 update_roles → P6 set_blocking → show → status ready.
        On any failure: document stays hidden, status failed, log_action, re-raise.
        Errors: NotFound, InvalidInput (unknown role), ServiceError."""

    def set_status(self, doc_id: str, status: str, error: str | None = None) -> None:
        """The only way to change a document's status. Errors: NotFound, InvalidInput (bad transition)."""

    def get_status(self, doc_id: str) -> str:
        """Current DocStatus of a document. Errors: NotFound."""

    def set_content_hash(self, doc_id: str, content_hash: str) -> None:
        """Stores make_content_hash(normalize_ar(full text)), computed by P1 after extraction.
        Errors: NotFound."""

    def create_document(
        self,
        file_bytes: bytes,
        file_name: str,
        meta: DocumentMeta,
        owner_id: UUID | None,
        uploaded_by: UUID | None,
    ) -> tuple[str, Path]:
        """Computes doc_id, stores the file in storage/uploads/, inserts the documents row
        (status received), logs DOCUMENT_UPLOAD. Returns (doc_id, stored file path).
        Used by POST /documents and by P1's command line. owner_id must be an existing user.
        Errors: Conflict (same doc_id exists), InvalidInput (format, size)."""


class Audit(Protocol):
    def log_query(self, request_id: UUID, user_id: UUID, query: str, latency_ms: int) -> None:
        """latency_ms: time from the start of the /ask request to the end of its stream,
        stored in audit_log.latency_ms."""

    def log_action(self, user_id: UUID | None, action_type: str, details: dict) -> None:
        """user_id is None when no user is behind the action: a background job (P1 ingestion,
        publication called from it) or a login with an unknown username.
        audit_log.request_id is filled from the current request's context variable."""
```

FastAPI dependencies (`src/api/deps.py`): `get_current_user_context(token) -> UserContext` (raises `Unauthenticated`), `require_roles(allowed_roles: list[str])` (raises `Forbidden`), `record_audit_event(context, action)`.

Stream helper (`src/api/deps.py`, P5, day 2), used by P3's `/ask` route:

```python
async def audited_stream(
    ctx: UserContext, question: str, events: AsyncIterator[dict]
) -> AsyncIterator[dict]:
    """Yields every event of `events`, then {"event": "done", "data": {request_id, latency_ms}},
    and calls log_query(ctx.request_id, ctx.user_id, question, latency_ms) in a finally block."""
```

### 6.2 Provided by P1

```python
class Ingestion(Protocol):
    def ingest(
        self,
        doc_id: str,
        file_path: Path,
        meta: DocumentMeta,
        roles: list[str],
        owner_id: UUID | None,
    ) -> None:
        """Runs in the background. Extract → normalize → chunk → P2 index → P6 register →
        set_status(indexed) → P5 set_document_roles(doc_id, roles).
        Calls set_status at each step; on failure set_status(failed, error) and stops."""

    def delete(self, doc_id: str) -> None:
        """Removes chunks from P2, fingerprints from P6, and the cache entry if unused.
        Idempotent: deleting a missing document is not an error."""
```

P1 also provides `normalize_ar(text: str) -> str` in `src/ingestion/normalize.py`, the single Arabic normalization used by P1 (chunks), P2 (queries, BM25), P3 (empty sub-questions and reformulations), P4 (excerpt check) and P6 (fingerprints). Its rules are in the P1 spec (P1-15).

### 6.3 Provided by P2

```python
class Retrieval(Protocol):
    """update_roles, hide, show and delete change all chunks of the document at once,
    are idempotent, and do nothing (no error) for a doc_id with no chunks. Errors: ServiceError."""

    def index(self, chunks: list[Chunk]) -> None:
        """Embeds and stores chunks, hidden. All chunks belong to one doc_id.
        Re-indexing the same chunk_id overwrites it, and any stored chunk of that doc_id
        with chunk_index >= total_chunks is deleted (left over from an older, longer version)."""

    def search(self, query: str, ctx: UserContext, top_k: int | None = None) -> list[Passage]:
        """Hybrid search, filtered BEFORE search by the visibility rule below.
        top_k None means retrieval.top_k_final.
        Errors: InvalidInput if ctx is missing."""

    def update_roles(self, doc_id: str, roles: list[str]) -> None:
        """Sets allowed_roles on every chunk of the document. Does not change hidden."""

    def hide(self, doc_id: str) -> None: ...
    def show(self, doc_id: str) -> None: ...
    def delete(self, doc_id: str) -> None: ...
```

**Visibility rule** (the exact condition applied inside Qdrant and BM25):

```
visible(chunk, ctx) =
    chunk is not hidden
    AND ( chunk.owner_id == ctx.user_id
          OR ctx.role in chunk.allowed_roles )
```

### 6.4 Provided by P6

```python
class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str: ...
    def stream(
        self, messages: list[dict], *, model: str | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]: ...
    def count_tokens(self, text: str) -> int: ...


class OCRClient(Protocol):
    def ocr_page(self, image: bytes, lang: str = "ar") -> tuple[str, float]:
        """image: an encoded PNG or JPEG file. Returns (text, confidence 0–1)."""


class LeakIndex(Protocol):
    def register(self, doc_id: str, text: str) -> None:
        """Stores fingerprints; blocking=True until set_blocking says otherwise."""

    def set_blocking(self, doc_id: str, blocking: bool) -> None: ...
    def delete(self, doc_id: str) -> None: ...


class ModelsClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """bge-m3 vectors (1024 floats each), same order as texts. Errors: ServiceError."""

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Re-ranker scores, same order as texts, higher is better. Errors: ServiceError."""


class WebSearch(Protocol):  # used only inside P6's web agent
    def search(
        self, query: str, max_results: int = 5, request_id: UUID | None = None
    ) -> list[WebResult]:
        """Errors: LeakBlocked (carries `hits`) if the query overlaps protected text; ServiceError
        for every other failure (web disabled, timeout, connection error, 5xx)."""


class WebAgent(Protocol):  # the only web entry point for other parts (P3)
    def lookup(
        self, question: str, ctx: UserContext, language: str, use_web: bool = True
    ) -> WebLookup:
        """Checks the switches (config web.enabled, ctx.web_enabled, use_web), builds a generic
        query from the question only, calls WebSearch.
        Never raises for disabled/blocked/offline: returns status "skipped"."""
```

### 6.5 Provided by P3

```python
class Orchestrator(Protocol):
    def run(self, question: str, ctx: UserContext, use_web: bool = True) -> AsyncIterator[dict]:
        """Yields the SSE events of §5.7 in order: thinking*, then answer or error.
        The /ask route adds the final `done` event (it measures the latency).
        Passes use_web unchanged to WebAgent.lookup."""
```

### 6.6 Provided by P4

```python
class Writer(Protocol):
    def write(
        self,
        question: str,
        passages: list[Passage],
        web: list[WebResult],
        ctx: UserContext,
        emit: Callable[[ProcessEvent], None] | None = None,
    ) -> Answer:
        """Writes, then verifies with the Juge. Returns status unknown if nothing is supported.
        After the Juge, calls emit(ProcessEvent(step="verify", ...)) if emit is given,
        so P3 can narrate it."""


class Narrator(Protocol):
    def narrate(self, event: ProcessEvent, language: str) -> AsyncIterator[str]:
        """Yields narration text for one process event."""
```

---

## 7. Errors

```python
# src/core/contracts/errors.py
class AppError(Exception):
    code: str = "app_error"
    http_status: int = 500


class InvalidInput(AppError):
    code, http_status = "invalid_input", 422


class Unauthenticated(AppError):
    code, http_status = "unauthenticated", 401


class Forbidden(AppError):
    code, http_status = "forbidden", 403


class NotFound(AppError):
    code, http_status = "not_found", 404


class Conflict(AppError):
    code, http_status = "conflict", 409


class LeakBlocked(AppError):
    code, http_status = (
        "leak_blocked",
        200,
    )  # internal to P6, never mapped to HTTP; carries `hits: int`


class TooManyRequests(AppError):
    code, http_status = "too_many_requests", 429


class ServiceError(AppError):
    code, http_status = "service_error", 503
```

- The API turns any `AppError` into `{"code": ..., "message": ...}` with its `http_status`, and any other exception into `500 {"code": "internal_error", "message": …}` with no details (P5-05).
- A document the user may not see is answered with `NotFound`, never `Forbidden`, so its existence is not revealed.
- Error messages never contain document text, titles of restricted documents, or the question.

---

## 8. HTTP API

| Method | Path | Body / query | Response | Access |
|---|---|---|---|---|
| POST | `/auth/login` | `{username, password}` | `{access_token, token_type: "bearer"}` | anyone |
| POST | `/auth/account-requests` | `AccountRequestIn` | `202 {request_id, status: "pending"}` | anyone (no token) |
| GET | `/auth/me` | — | `MeResponse` | any user |
| POST | `/documents` | multipart: `file`, `title`, `source` (optional), `date` (optional), `roles` (editors only, sent as repeated fields: `roles=lecteur&roles=editeur`); at most `uploads.max_bytes` | `202 {doc_id, status}` | `editeur`; any user for a private upload |
| GET | `/documents` | — | `list[DocumentResponse]` | any user (see below) |
| GET | `/documents/{doc_id}/status` | — | `{doc_id, status, error, duplicate_of}` | uploader; `editeur` (corpus documents) |
| DELETE | `/documents/{doc_id}` | — | `204` | uploader; `editeur` and `admin` (corpus documents) |
| POST | `/search` | `{query, top_k}` | `list[Passage]` | any user |
| POST | `/ask` | `{question, use_web: bool = true}` | SSE stream (§5.7) | any user |
| GET | `/conversations` | — | `list[ConversationResponse]` | any user (own conversations) |
| POST | `/conversations` | — | `201 ConversationResponse` | any user |
| GET | `/conversations/{conversation_id}` | — | `ConversationDetail` | owner |
| POST | `/conversations/{conversation_id}/messages` | `MessageIn` | `201 MessageResponse` | owner |
| DELETE | `/conversations/{conversation_id}` | — | `204` | owner |
| GET | `/admin/users` | — | `list[UserResponse]` | `admin` |
| POST | `/admin/users` | `UserCreate` | `UserResponse` | `admin` |
| PATCH | `/admin/users/{user_id}/role` | `{role_id}` | `UserResponse` | `admin` |
| PATCH | `/admin/users/{user_id}/active` | `{is_active: bool}` | `UserResponse` | `admin` |
| GET | `/admin/roles` | — | `list[RoleResponse]` | `admin` |
| PATCH | `/admin/roles/{role_id}/web` | `{web_enabled: bool}` | `{role_id, name, web_enabled}` | `admin` |
| PUT | `/admin/documents/{doc_id}/roles` | `{roles: list[str]}` | `{doc_id, status}` | `admin`; corpus documents only (`404` for a private upload) |
| GET | `/admin/audit` | `?limit=100` | `list[AuditLogResponse]` | `admin` |
| GET | `/admin/account-requests` | `?status=pending` | `list[AccountRequestResponse]` | `admin` |
| POST | `/admin/account-requests/{request_id}/approve` | `{role_id}` | `UserResponse` | `admin` |
| POST | `/admin/account-requests/{request_id}/reject` | — | `204` | `admin` |

Every request except `/auth/login`, `/auth/account-requests` and `/health` carries `Authorization: Bearer <token>`.

**User, session and listing models**

```python
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


class MeResponse(BaseModel):
    user_id: UUID
    username: str
    role: str  # a RoleName value
    web_available: bool  # config web.enabled AND roles.web_enabled of the user's role


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


class RoleResponse(BaseModel):
    role_id: int
    name: str
    web_enabled: bool
```

`GET /documents` lists: the user's own private uploads, for every user; plus every corpus document, for `editeur` and `admin`. Never another user's private upload.

**Account request models**

```python
class AccountRequestIn(BaseModel):
    username: str  # 3–32 characters: letters, digits, "." "_" "-"
    password: str  # at least auth.min_password_length characters
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
```

- A request does not create a user. The user is created only when an admin approves it, with the role the admin chooses.
- Until then the person cannot log in: `/auth/login` answers the same `401` as for an unknown username.

**Conversation history models**

```python
class ConversationResponse(BaseModel):
    conversation_id: UUID
    title: str | None  # the first question, cut to 60 characters; None before it
    created_at: datetime
    updated_at: datetime  # time of the last exchange


class MessageIn(BaseModel):
    question: str  # as sent to /ask
    answer: Answer  # as received in the `answer` event (§5.7)


class MessageResponse(BaseModel):
    position: int  # 1, 2, 3… within the conversation
    question: str
    available: bool  # False: a cited document is no longer visible to the user
    answer: Answer | None  # None when available is False
    language: str  # answer.language, kept to show the notice below
    created_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]  # by position
```

- A conversation belongs to one user. Every route answers `404` for another user's conversation, never `403`. No route lets the admin read conversations.
- The API saves what P7 sends; it never sends earlier exchanges to `/ask`. Each question is still answered alone.
- Saved: the question and the `Answer`. Never the thinking stream or the passages.
- When a conversation is opened, an exchange is `available` only if every document cited in its answer still exists, is `ready`, and is visible to this user (owner, or the user's role in `document_roles`). Otherwise `answer` is `None` and P7 shows the fixed notice "هذه الإجابة لم تعد متاحة." ("Cette réponse n'est plus disponible." for `language = "fr"`). A deleted document and a restricted one give the same result. An answer that cites no document (`unknown`, or web only) is always available.

---

## 9. Getting an implementation: fakes and real

```python
# src/core/contracts/registry.py
def get_retrieval() -> Retrieval: ...
def get_ingestion() -> Ingestion: ...
def get_document_rights() -> DocumentRights: ...
def get_audit() -> Audit: ...
def get_llm() -> LLMClient: ...
def get_ocr() -> OCRClient: ...
def get_leak_index() -> LeakIndex: ...
def get_web_search() -> WebSearch: ...
def get_web_agent() -> WebAgent: ...
def get_models() -> ModelsClient: ...
def get_orchestrator() -> Orchestrator: ...
def get_writer() -> Writer: ...
def get_narrator() -> Narrator: ...
```

Each `get_*` reads `config.yaml → contracts.<name>` (`fake` or `real`) and returns the matching implementation. Business code only ever calls `get_*`; it never imports a fake or a real implementation directly.

Each `get_*` returns **one instance per process**, created on the first call and then reused, so a fake keeps its state across calls (e.g. `FakeLLMClient`'s list of replies, P2's in-memory BM25). In tests, `registry.override(name, instance)` replaces an instance and `registry.reset()` clears them all. File-based fakes write under `fakes.data_dir`, which tests point at a temporary folder.

Where `registry.py` finds them (each real factory takes no argument and reads `cfg` itself):

| Contract | Fake (`src/core/contracts/fakes/…`) | Real factory |
|---|---|---|
| `retrieval` | `retrieval.py:FakeRetrieval` | `src/retrieval/__init__.py:real_retrieval()` |
| `ingestion` | `ingestion.py:FakeIngestion` | `src/ingestion/__init__.py:real_ingestion()` |
| `document_rights` | `rights.py:FakeDocumentRights` | `src/core/db/rights.py:real_document_rights()` |
| `audit` | `audit.py:FakeAudit` | `src/core/audit.py:real_audit()` |
| `llm` | `llm.py:FakeLLMClient` | `src/core/llm/__init__.py:real_llm()` |
| `ocr` | `llm.py:FakeOCRClient` | `src/core/llm/__init__.py:real_ocr()` |
| `models` | `llm.py:FakeModelsClient` | `src/core/llm/__init__.py:real_models()` |
| `leak_index` | `leak.py:FakeLeakIndex` | `src/core/leak/__init__.py:real_leak_index()` |
| `web_search` | `web.py:FakeWebSearch` | `src/agents/web/__init__.py:real_web_search()` |
| `web_agent` | `web.py:FakeWebAgent` | `src/agents/web/__init__.py:real_web_agent()` |
| `orchestrator` | `orchestrator.py:FakeOrchestrator` | `src/agents/orchestrator/__init__.py:real_orchestrator()` |
| `writer` | `answer.py:FakeWriter` | `src/agents/answer/__init__.py:real_writer()` |
| `narrator` | `answer.py:FakeNarrator` | `src/agents/answer/__init__.py:real_narrator()` |

| Fake | Behaviour |
|---|---|
| `FakeRetrieval` | `index` replaces that document's chunks in `data/processed/chunks.jsonl`, stored hidden; `update_roles`, `hide`, `show`, `delete` change that file; `search` returns chunks that pass the visibility rule (hidden flag included), by simple word overlap |
| `FakeIngestion` | `ingest` copies the chunks of `tests/fixtures/sample_chunks.jsonl`, rewrites `doc_id`, `chunk_id`, `chunk_index`, `total_chunks`, `title`, `source_file`, `source`, `date` and `owner_id` from its arguments, sets `allowed_roles = []`, then calls `set_status` (extracting, chunked), `index`, `set_status(indexed)` and `set_document_roles(doc_id, roles)` |
| `FakeDocumentRights` | Stores rights and statuses in `data/processed/fake_documents.json` |
| `FakeAudit` | Appends to `data/processed/fake_audit.jsonl` |
| `FakeLLMClient` | `chat` returns the next reply from a configurable list (or one fixed string); `stream` yields that reply word by word; `count_tokens` = word count |
| `FakeOCRClient` | Returns a fixed Arabic sentence with confidence 0.9 |
| `FakeLeakIndex` | In-memory sets of 4-grams, no HMAC |
| `FakeWebSearch` | Returns two fixed `WebResult`s; raises `LeakBlocked` if the query contains `"LEAK"` |
| `FakeWebAgent` | `skipped` if `use_web` is false, `ctx.web_enabled` is false, `web.enabled` is false, or the question contains `"LEAK"`, else `done` with two fixed results |
| `FakeModelsClient` | `embed`: deterministic vectors from a hash of each text; `rerank`: word-overlap scores |
| `FakeOrchestrator` | Yields 3 `thinking` events and a fixed `answer` |
| `FakeWriter` | Returns an `Answer` citing the first passage (or the unknown answer if there are no passages and no web results), and calls `emit` with one `verify` event when it had passages or web results |
| `FakeNarrator` | Yields one template sentence per event |

**Who writes what**

| Piece | Written by | When |
|---|---|---|
| A contract's Protocol, fake and contract test | The part that provides the contract | Days 1–2 |
| `src/core/contracts/registry.py` (all `get_*` functions) | P5, as part of the skeleton | Day 1 |
| `tests/conftest.py`: user fixtures (`*_ctx`) | P5 | Day 1 |
| `tests/conftest.py`: `sample_chunks` fixture + `tests/fixtures/sample_chunks.jsonl` | P1 | Days 1–2 |

**Who runs what**
- CI runs **all** contract tests on every PR, whoever the author is.
- The fake version of each test runs from day 1. The real version is skipped automatically until that part's real implementation exists; CI starts Postgres and Qdrant as service containers for it.
- Locally: `pytest tests/contracts`.

**Contract tests** live in `tests/contracts/test_<name>.py`. Each test is parametrized over the fake and the real implementation, so both must pass it. Shared fixtures in `tests/conftest.py`: `lecteur_ctx`, `editeur_ctx`, `admin_ctx`, `other_lecteur_ctx` (each with a fixed `user_id`, so sample chunks can name an owner), and `sample_chunks` (the ~20 sample chunks from P1).

---

## 10. `config.yaml` keys

```yaml
mode: local                 # local | light | cloud
fakes:
  data_dir: data/processed  # where file-based fakes write (tests use a temporary folder)
contracts:                  # fake | real, per contract
  retrieval: fake
  ingestion: fake
  document_rights: fake
  audit: fake
  llm: fake
  ocr: fake
  leak_index: fake
  web_search: fake
  web_agent: fake
  models: fake
  orchestrator: fake
  writer: fake
  narrator: fake
llm:
  model: qwen2.5:7b
  model_light: qwen2.5:3b
  narration_model: qwen2.5:1.5b
  num_ctx: 16384             # Ollama context window, passed as options.num_ctx
  base_url: http://llm:11434
models:
  base_url: http://models:8080
  embedding: BAAI/bge-m3
  reranker: BAAI/bge-reranker-v2-m3
retrieval:
  qdrant_url: http://qdrant:6333
  collection: chunks
  embed_batch_size: 32
  top_k_vector: 30
  top_k_bm25: 30
  rrf_k: 60
  top_k_final: 10             # default top_k of search()
  rerank_top_n: 20            # fused chunks sent to the re-ranker; also the maximum top_k
agents:
  max_iterations: 3           # searches per sub-question
  max_sub_questions: 3
  max_tokens_per_request: 8000  # P3's own LLM calls (plan, grade, reformulate)
  grade_top_n: 5              # passages graded per search
  min_relevant: 1             # relevant passages for a sub-question to count as answered
  max_passages_to_writer: 8
  max_question_chars: 1000
  request_timeout_s: 60
  confidence_unknown_below: 0.4
answer:
  max_answer_tokens: 800
  max_judge_tokens: 600
  min_excerpt_chars: 10
  web_confidence_cap: 0.5     # answers citing only web sources
  narration_max_tokens: 60
web:
  enabled: true               # global switch (e.g. off for the offline demo); per-role switch is roles.web_enabled
  base_url: http://web-search:8090
  max_results: 5
  max_query_words: 12
  max_snippet_chars: 500
  timeout_s: 5
leak:
  ngram: 4
  overlap_threshold: 0.2      # starting value, tuned on the leak tests
  min_hits: 3
  max_df: 20
ocr:
  base_url: http://ocr:8070
  max_pages_upload: 50
database:                   # PostgreSQL (P5); the password is POSTGRES_PASSWORD in .env
  host: postgres            # the compose service, on the internal network
  port: 5432
  name: rag
  user: postgres
auth:
  token_minutes: 60
  max_failed_logins: 5
  lockout_minutes: 15
  min_password_length: 8
  max_pending_requests: 50    # POST /auth/account-requests answers 429 once this many are pending
ui:
  api_base_url: http://api:8000   # the ui service also reads agents.max_question_chars and auth.min_password_length
uploads:
  max_bytes: 20000000         # 20 MB per file
ingestion:
  strategy: article           # article | fixed
  max_chunk_chars: 2000
  overlap_chars: 200
  min_letters_per_page: 50
  ocr_min_confidence: 0.6
```

---

## 11. Worked example

One document, followed through every part.

**Upload.** An editor uploads `circulaire_12_2025.pdf` (a digital PDF, 3 pages) with `roles = ["editeur"]` (an internal circular).

```
doc_id    = make_doc_id(file_bytes, None)   → "a3f9…e21"   (scope "corpus")
file_hash = make_file_hash(file_bytes)      → "77c0…b4d"
meta      = DocumentMeta(title="دورية رقم 12", source_file="circulaire_12_2025.pdf",
                         source="مديرية الشؤون القانونية — مذكرة داخلية")
P5: insert documents(id="a3f9…e21", title=…, source_file=…, source=…)
P5 → 202 {doc_id: "a3f9…e21", status: "received"}
P5: ingest("a3f9…e21", "storage/uploads/a3f9…e21.pdf", meta, ["editeur"], None)  [background]
```

**Ingestion (P1).** `set_status(extracting)` → text extracted (no OCR needed) → normalized → 3 articles → `set_status(chunked)`.

```json
{"chunk_id": "make_chunk_id('a3f9…e21', 1)", "doc_id": "a3f9…e21",
 "chunk_index": 1, "total_chunks": 3,
 "text": "المادة 2: يتعين على المصالح المختصة معالجة الطلبات داخل أجل ثلاثين يوما.",
 "text_normalized": "الماده 2 يتعين علي المصالح المختصه معالجه الطلبات داخل اجل ثلاثين يوما",
 "title": "دورية رقم 12", "article": "المادة 2", "hierarchy": [],
 "page_start": 1, "page_end": 1, "language": "ar",
 "source_file": "circulaire_12_2025.pdf", "source": "مديرية الشؤون القانونية — مذكرة داخلية", "date": null,
 "allowed_roles": [], "owner_id": null}
```

P1 → P2 `index(3 chunks)` (hidden) → P6 `register("a3f9…e21", text)` (blocking) → `set_status(indexed)` → P5 `set_document_roles("a3f9…e21", ["editeur"])`.

**Publication (P5).** `hide` → `document_roles = [(a3f9…e21, editeur)]` → P2 `update_roles(…, ["editeur"])` → P6 `set_blocking(…, True)` (not public: `"lecteur"` is not in the roles) → `show` → `set_status(ready)` → `log_action`.

**An editeur (jurist) asks** "ما هو أجل معالجة الطلبات حسب الدورية 12؟"

```
ctx = UserContext(role="editeur", …)
P2 search → chunk 1 visible ("editeur" in chunk.allowed_roles) → rank 1
P4 answer:
  {"status": "answered",
   "text": "حدد أجل معالجة الطلبات في ثلاثين يوما [1].",
   "citations": [{"doc_id": "a3f9…e21", "title": "دورية رقم 12", "article": "المادة 2",
                  "page": 1, "source": "مديرية الشؤون القانونية — مذكرة داخلية",
                  "excerpt": "معالجة الطلبات داخل أجل ثلاثين يوما"}],
   "confidence": 0.86, "language": "ar"}
```

**A lecteur (citizen) asks the same question.** `ctx.role = "lecteur"`, not in `["editeur"]`. P2's filter excludes the 3 chunks before search, so nothing from the circular is ever retrieved. Answer: `status = "unknown"`, text "لم أجد هذه المعلومة في الوثائق المتاحة لك.", with no title, excerpt or hint that the circular exists. The same text is given when the corpus simply does not cover a question.

**The web.** If the web query built by P6's web agent were "أجل معالجة الطلبات داخل ثلاثين يوما", the `web-search` filter would find its 4-grams in the circular's fingerprints → blocked → `WebLookup(status="skipped")` → the narration says "web search skipped".
