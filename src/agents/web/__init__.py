"""Real WebSearch and WebAgent implementations (P6-17 to P6-28)."""

from __future__ import annotations

import logging
import os
from uuid import UUID, uuid4

import httpx

from src.core.config import cfg
from src.core.contracts.enums import AuditAction
from src.core.contracts.errors import LeakBlocked, ServiceError
from src.core.contracts.models import UserContext, WebLookup, WebResult
from src.core.contracts.registry import get_audit, get_llm, get_web_search

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "fr": "French",
    "ar": "Modern Standard Arabic",
}

REFORMULATE_PROMPT = """Rewrite the user's question as a short web search query, in {language}.
Rules: at most {max_words} words; keep only the general legal topic;
remove names of people, organisations, places, document numbers, dates and figures;
answer with the query only."""


class HttpWebSearch:
    """HTTP client for the internal web-search service."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_s: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("LEAK_API_TOKEN", "")
        if not self.token:
            raise ServiceError("Web search authentication is not configured")

        self.client = client or httpx.Client(
            base_url=(base_url or cfg.web.base_url).rstrip("/"),
            timeout=timeout_s if timeout_s is not None else cfg.web.timeout_s,
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def search(
        self,
        query: str,
        max_results: int = 5,
        request_id: UUID | None = None,
    ) -> list[WebResult]:
        """Search through web-search; never expose service errors to the caller."""
        payload = {
            "query": query,
            "max_results": max_results,
            "request_id": str(request_id or uuid4()),
        }

        try:
            response = self.client.post(
                "/search",
                json=payload,
                headers=self.headers,
            )
        except httpx.HTTPError as exc:
            raise ServiceError("Web search service unavailable") from exc

        if response.status_code == 403:
            try:
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Invalid error response")

                if body.get("code") == "leak_blocked":
                    hits = int(body.get("hits", 0))
                    if hits < 0:
                        raise ValueError("Invalid hit count")
                    raise LeakBlocked("Search query blocked", hits=hits)
            except LeakBlocked:
                raise
            except (ValueError, TypeError, AttributeError) as exc:
                raise ServiceError("Invalid error response from web search") from exc

            raise ServiceError("Web search service refused the request")

        if response.is_error:
            raise ServiceError("Web search service failed")

        try:
            body = response.json()
            return [WebResult.model_validate(item) for item in body["results"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("Invalid response from web search service") from exc


class RealWebAgent:
    """Privacy-preserving web lookup agent."""

    def lookup(
        self,
        question: str,
        ctx: UserContext,
        language: str,
        use_web: bool = True,
    ) -> WebLookup:
        # Check every switch before invoking the LLM or the network.
        if not (cfg.web.enabled and ctx.web_enabled and use_web):
            return WebLookup(status="skipped", results=[])

        try:
            query = get_llm().chat(
                [
                    {
                        "role": "system",
                        "content": REFORMULATE_PROMPT.format(
                            language=LANGUAGE_NAMES[language],
                            max_words=cfg.web.max_query_words,
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                max_tokens=40,
            )

            query = " ".join(query.split()[: cfg.web.max_query_words])
            if not query:
                return WebLookup(status="skipped", results=[])

            results = get_web_search().search(
                query,
                cfg.web.max_results,
                request_id=ctx.request_id,
            )

        except LeakBlocked as exc:
            try:
                get_audit().log_action(
                    ctx.user_id,
                    AuditAction.WEB_BLOCKED.value,
                    {
                        "request_id": str(ctx.request_id),
                        "hits": exc.hits,
                    },
                )
            except Exception as audit_exc:
                logger.warning(
                    "web blocked audit failed",
                    extra={"reason": type(audit_exc).__name__},
                )
            return WebLookup(status="skipped", results=[])

        except (ServiceError, TimeoutError):
            return WebLookup(status="skipped", results=[])

        except Exception as exc:
            logger.warning(
                "web lookup skipped",
                extra={"reason": type(exc).__name__},
            )
            return WebLookup(status="skipped", results=[])

        truncated = [
            result.model_copy(update={"snippet": result.snippet[: cfg.web.max_snippet_chars]})
            for result in results[: cfg.web.max_results]
        ]

        return WebLookup(status="done", results=truncated)


def real_web_search() -> HttpWebSearch:
    """Factory used by the service registry."""
    return HttpWebSearch()


def real_web_agent() -> RealWebAgent:
    """Factory used by the service registry."""
    return RealWebAgent()
