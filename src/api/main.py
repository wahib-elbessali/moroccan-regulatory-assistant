import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from src.api.routes import admin, ask, auth, conversations, documents, search
from src.core.contracts.errors import AppError
from src.core.db.init_db import init_db
from src.core.logging import request_id_ctx_var, setup_logging
from src.core.security import request_id_var

setup_logging()


logger = logging.getLogger("rag_api")


def _parse_valid_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run Alembic migrations, seed initial admin, and mark interrupted jobs failed (P5-10b, P5-12, P5-12b)."""
    init_db()
    yield


app = FastAPI(
    title="Regulatory Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Set request_id before authentication and echo X-Request-ID in response (P5-02)."""
    rid = _parse_valid_uuid(request.headers.get("X-Request-ID")) or uuid4()
    sec_token = request_id_var.set(rid)
    log_token = request_id_ctx_var.set(rid)
    request.state.request_id = str(rid)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.headers["X-Request-ID"] = str(rid)
        return response
    finally:
        request_id_ctx_var.reset(log_token)
        request_id_var.reset(sec_token)


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    """Turn any domain AppError into {"code", "message"} with its HTTP status (P5-05)."""
    rid = request_id_var.get()
    headers = {"X-Request-ID": str(rid)} if rid else None
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message},
        headers=headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Mask internal exceptions behind 500 {"code": "internal_error"} without details (P5-05)."""
    logger.exception("unhandled_exception", extra={"event": "unhandled_exception"})
    rid = request_id_var.get()
    headers = {"X-Request-ID": str(rid)} if rid else None
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error"},
        headers=headers,
    )


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
