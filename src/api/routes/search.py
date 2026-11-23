"""POST /search: the best passages this user may see (P2-28, 00-shared §8).

The route is deliberately thin. Everything that matters already lives behind
``Retrieval.search`` (``src/retrieval/search.py``), and repeating any of it here would create a
second place to keep in step:

* **Access control.** The route's only security job is to hand the pipeline the ``UserContext``
  built by P5's ``get_current_user_context``. The visibility rule (00-shared §6.3) is applied
  *inside* Qdrant and *before scoring* in BM25 (P2-12, P2-13), so the route never filters,
  reorders or truncates what comes back. The body carries the query and ``top_k`` and nothing
  else: ``user_id``, ``role`` and ``allowed_roles`` are not fields of ``SearchRequest``, so a
  client that sends them is simply ignored, and ``UserContext`` is frozen anyway.
* **Validation.** ``search`` raises ``InvalidInput`` for a missing context, a query that is empty
  after ``normalize_ar``, or a ``top_k`` outside ``1 … retrieval.rerank_top_n`` (P2-11). Those
  checks are *not* repeated as pydantic constraints: two sets of rules would answer the same
  mistake in two different shapes, and ``FakeRetrieval`` applies exactly the same ones.
* **Errors.** ``src/api/main.py`` turns any ``AppError`` into ``{"code", "message"}`` with its
  ``http_status`` (P5-05), so ``InvalidInput`` is already a 422, ``Unauthenticated`` a 401 and
  ``ServiceError`` a 503. There is no ``try``/``except`` here: catching them would only replace
  that one format with another.
* **Logs.** ``search`` writes the single structured line per search required by P2-29. The route
  adds none, and in particular never logs the query or any chunk text.

Nothing is audited: ``AuditAction`` (00-shared §4) has no value for a search — ``QUERY_ASK``
belongs to ``/ask`` — and no requirement asks for one.

The handler is a plain ``def``. ``search`` is synchronous and slow (it waits on Qdrant and on
P6's models service; the Sat 11-21 run measured a median of 53 s), so FastAPI runs it in a
worker thread. An ``async def`` would hold the event loop for that whole time and freeze every
other request, ``/health`` and ``/ask``'s stream included.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.contracts.models import Passage, UserContext
from src.core.contracts.registry import get_retrieval
from src.core.security import get_current_user_context

router = APIRouter()


class SearchRequest(BaseModel):
    """The body of ``POST /search`` (00-shared §8)."""

    query: str = Field(description="The question, as typed. Arabic, French or mixed.")
    top_k: int | None = Field(
        default=None,
        description=(
            "How many passages to return, 1 … retrieval.rerank_top_n. "
            "Omitted or null means retrieval.top_k_final."
        ),
    )


@router.post("")
@router.post("/")
def search(
    body: SearchRequest,
    ctx: UserContext = Depends(get_current_user_context),  # noqa: B008
) -> list[Passage]:
    """The passages this user is allowed to see, best first (P2-28).

    ``top_k`` is passed through as it arrives, ``None`` included: the default belongs to
    ``Retrieval.search``, which applies ``retrieval.top_k_final`` for ``None`` (00-shared §6.3).
    P2-28 writes that default into the body instead; reading ``cfg`` here, as a pydantic field
    default, would load the configuration when this module is imported and freeze the value for
    the life of the process. The behaviour is the same, and the rule stays in one place.

    ``get_retrieval()`` is called here, per request, and never at import time: it is what honours
    ``contracts.retrieval`` (fake or real) in ``config.yaml``, and what lets a test install its
    own implementation with ``registry.override``.

    Returns:
        At most ``top_k`` passages, ``rank`` 1, 2, 3…, by decreasing score. ``[]`` when nothing
        visible matches — an empty result is a normal 200, not a 404 (P2-17).

    Raises:
        Unauthenticated: No bearer token, an invalid one, or an inactive user (401, P5-19).
        InvalidInput: Empty query, or ``top_k`` out of range (422, P2-11).
        ServiceError: Qdrant is unreachable (503, P2 spec §7).
    """
    return get_retrieval().search(body.query, ctx, body.top_k)
