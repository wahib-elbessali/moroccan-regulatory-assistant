"""Fake implementations of the WebSearch and WebAgent protocols (P6)."""

import logging
from uuid import UUID

from ..errors import LeakBlocked
from ..models import UserContext, WebLookup, WebResult
from ..protocols import WebSearch

logger = logging.getLogger(__name__)


def _fixed_results() -> list[WebResult]:
    """Returns fresh deterministic results for contract tests."""
    return [
        WebResult(
            url="https://example.org/reglementation-fiscale-maroc",
            title="Mock Moroccan tax regulations",
            snippet="Mock result about Moroccan tax regulations.",
        ),
        WebResult(
            url="https://example.org/code-general-impots",
            title="Mock General Tax Code",
            snippet="Mock result about the General Tax Code.",
        ),
    ]


class FakeWebSearch:
    """Deterministic in-memory fake of the WebSearch protocol."""

    def search(
        self,
        query: str,
        max_results: int = 5,
        request_id: UUID | None = None,
    ) -> list[WebResult]:
        """Returns two fixed results, unless the query contains the leak sentinel."""
        if "LEAK" in query:
            raise LeakBlocked("protected content detected", hits=1)

        return _fixed_results()[:max_results]


class FakeWebAgent:
    """Deterministic fake of the WebAgent protocol."""

    def __init__(
        self,
        *,
        web_enabled: bool = True,
        web_search: WebSearch | None = None,
    ) -> None:
        self._web_enabled = web_enabled
        self._web_search = web_search if web_search is not None else FakeWebSearch()

    def lookup(
        self,
        question: str,
        ctx: UserContext,
        language: str,
        use_web: bool = True,
    ) -> WebLookup:
        """Returns skipped when web is unavailable or blocked; otherwise returns results."""
        if not self._web_enabled or not ctx.web_enabled or not use_web or "LEAK" in question:
            return WebLookup(status="skipped", results=[])

        try:
            results = self._web_search.search(
                question,
                request_id=ctx.request_id,
            )
        except Exception as exc:
            logger.warning("web lookup skipped", extra={"reason": type(exc).__name__})
            return WebLookup(status="skipped", results=[])

        return WebLookup(status="done", results=results)
