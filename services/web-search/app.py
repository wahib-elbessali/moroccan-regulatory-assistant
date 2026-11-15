"""Authenticated web-search service and leak-protection API (P6-23 to P6-35)."""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from leak_filter import LeakFilter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.responses import JSONResponse, Response
from store import SQLiteLeakStore

logger = logging.getLogger("web_search")
logging.basicConfig(level=logging.INFO, format="%(message)s")

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/app/config.yaml"))
DATABASE_PATH = Path(os.getenv("LEAK_DB_PATH", "/data/leak.sqlite3"))
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080")


# HMAC fingerprints are 16 lowercase hex characters (src/core/leak/fingerprint.py).
# Anything else is refused, so raw text can never end up in the index (P6-29).
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=20)
    request_id: UUID


class WebResult(BaseModel):
    url: str
    title: str
    snippet: str


class SearchResponse(BaseModel):
    results: list[WebResult]


class IndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=512)
    grams: list[Fingerprint] = Field(default_factory=list)
    refs: list[Fingerprint] = Field(default_factory=list)


class BlockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=512)
    blocking: bool


def read_config() -> dict:
    """Read the mounted configuration file."""
    with CONFIG_PATH.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}

    if not isinstance(config, dict):
        raise ValueError("Invalid configuration root")

    return config


def log_search(
    request_id: UUID,
    status: str,
    hits: int,
    started: float,
    *,
    query: str | None = None,
) -> None:
    """Emit exactly one structured log line; blocked queries are never included."""
    event = {
        "request_id": str(request_id),
        "status": status,
        "hits": hits,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }

    if status == "ok" and query is not None:
        event["query"] = query

    logger.info(json.dumps(event, ensure_ascii=False))


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = os.getenv("LEAK_API_TOKEN", "")
    key = os.getenv("LEAK_HMAC_KEY", "")

    if not token or not key:
        raise RuntimeError("LEAK_API_TOKEN and LEAK_HMAC_KEY are required")

    internal_cidr = os.getenv("INTERNAL_NETWORK_CIDR", "")

    try:
        internal_network = ipaddress.ip_network(internal_cidr, strict=True)
    except ValueError as exc:
        raise RuntimeError("INTERNAL_NETWORK_CIDR must be a valid network CIDR") from exc

    config = read_config()
    leak_config = config.get("leak", {})

    store = SQLiteLeakStore(DATABASE_PATH)
    leak_filter = LeakFilter(
        store,
        key.encode("utf-8"),
        ngram=int(leak_config.get("ngram", 4)),
        min_hits=int(leak_config.get("min_hits", 3)),
        max_df=int(leak_config.get("max_df", 20)),
        overlap_threshold=float(leak_config.get("overlap_threshold", 0.2)),
    )

    app.state.api_token = token
    app.state.internal_network = internal_network
    app.state.store = store
    app.state.leak_filter = leak_filter
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(float(config.get("web", {}).get("timeout_s", 5)))
    )

    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(
    title="Web Search Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


async def require_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.api_token

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated"},
        )

    supplied = authorization.removeprefix("Bearer ")

    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated"},
        )

    client = request.client

    if client is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden_network"},
        )

    try:
        client_ip = ipaddress.ip_address(client.host)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden_network"},
        ) from None

    if not (client_ip.is_loopback or client_ip in request.app.state.internal_network):
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden_network"},
        )


Authenticated = Annotated[None, Depends(require_token)]


@app.get("/health")
async def health(_: Authenticated) -> dict[str, str]:
    return {"status": "ok"}


@app.post("/index", status_code=204)
async def register_document(
    body: IndexRequest,
    request: Request,
    _: Authenticated,
) -> Response:
    request.app.state.store.register(body.doc_id, body.grams, body.refs)
    return Response(status_code=204)


@app.post("/blocking", status_code=204)
async def set_document_blocking(
    body: BlockingRequest,
    request: Request,
    _: Authenticated,
) -> Response:
    request.app.state.store.set_blocking(body.doc_id, body.blocking)
    return Response(status_code=204)


@app.delete("/index/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    request: Request,
    _: Authenticated,
) -> Response:
    request.app.state.store.delete(doc_id)
    return Response(status_code=204)


@app.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    request: Request,
    _: Authenticated,
):
    started = time.perf_counter()

    try:
        config = read_config()
        web_config = config.get("web", {})

        if not web_config.get("enabled", False):
            log_search(body.request_id, "disabled", 0, started)
            return JSONResponse(
                status_code=403,
                content={"code": "web_disabled"},
            )

        max_query_words = int(web_config.get("max_query_words", 12))
        if len(body.query.split()) > max_query_words:
            log_search(body.request_id, "error", 0, started)
            return JSONResponse(
                status_code=422,
                content={"code": "invalid_query"},
            )

        blocked, hits = request.app.state.leak_filter.check(body.query)

        if blocked:
            log_search(body.request_id, "blocked", hits, started)
            return JSONResponse(
                status_code=403,
                content={"code": "leak_blocked", "hits": hits},
            )

        max_results = min(
            body.max_results,
            int(web_config.get("max_results", 5)),
        )
        snippet_limit = int(web_config.get("max_snippet_chars", 500))

        response = await request.app.state.http_client.get(
            f"{SEARXNG_URL}/search",
            params={
                "q": body.query,
                "format": "json",
                "pageno": 1,
            },
        )
        response.raise_for_status()

        payload = response.json()
        raw_results = payload.get("results", [])

        results = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            url = item.get("url")
            title = item.get("title")
            snippet = item.get("content", "")

            if not isinstance(url, str) or not isinstance(title, str):
                continue

            if not isinstance(snippet, str):
                snippet = ""

            results.append(
                {
                    "url": url,
                    "title": title,
                    "snippet": snippet[:snippet_limit],
                }
            )

            if len(results) >= max_results:
                break

        log_search(
            body.request_id,
            "ok",
            hits,
            started,
            query=body.query,
        )

        return {"results": results}

    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, httpx.HTTPError):
        log_search(body.request_id, "error", 0, started)
        return JSONResponse(
            status_code=503,
            content={"code": "search_unavailable"},
        )
