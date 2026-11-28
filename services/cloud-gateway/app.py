"""cloud-gateway: Ollama's ``/api/chat`` in front of a cloud LLM API (``cloud`` mode, dev only).

P6 spec §6.1, architecture §5. ``GatewayClient`` in ``api`` speaks to this service exactly as
``OllamaClient`` speaks to Ollama. The gateway turns each call into an OpenAI-compatible
``/chat/completions`` request (Groq, Mistral, OpenRouter… all accept it) and turns the answer back.

Only this service, ``web-search`` and ``searxng`` are on the ``egress`` network, and it only runs
under the compose profile ``cloud``. ``GatewayClient`` refuses to exist unless ``mode: cloud`` and
``ALLOW_CLOUD_LLM=true``; this service adds its own check: with no provider configured in ``.env``
it answers 503 and sends nothing.

Configuration (``.env``, never committed):
    CLOUD_API_BASE  e.g. https://api.groq.com/openai/v1
    CLOUD_API_KEY
    CLOUD_MODEL     the provider's model name; replaces the Ollama name sent by ``api``
    CLOUD_REASONING_TOKENS  optional, default 0: tokens added to every ``max_tokens``. A thinking
                    model spends part of ``max_tokens`` on hidden reasoning; with the app's small
                    budgets (100 for grading) it would return no text at all.

Prompts hold document passages, so nothing of a message or an answer is ever logged: only the
status, the number of messages and the latency.
"""

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("cloud_gateway")
logging.basicConfig(level=logging.INFO, format="%(message)s")

TIMEOUT_S = float(os.getenv("CLOUD_API_TIMEOUT_S", "120"))

app = FastAPI(title="cloud-gateway")


def provider() -> dict[str, str] | None:
    """The provider settings from the environment, or ``None`` when one of them is missing."""
    cfg = {
        "base_url": os.getenv("CLOUD_API_BASE", "").strip().rstrip("/"),
        "api_key": os.getenv("CLOUD_API_KEY", "").strip(),
        "model": os.getenv("CLOUD_MODEL", "").strip(),
    }
    return cfg if all(cfg.values()) else None


def to_openai(body: dict[str, Any], model: str) -> dict[str, Any]:
    """An Ollama ``/api/chat`` body as an OpenAI ``/chat/completions`` body."""
    options = body.get("options") or {}
    out: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in body.get("messages") or []
        ],
        "temperature": options.get("temperature", 0.0),
        "stream": bool(body.get("stream", True)),
    }
    if options.get("num_predict") is not None:
        out["max_tokens"] = options["num_predict"] + reasoning_tokens()
    return out


def reasoning_tokens() -> int:
    """Extra tokens for a thinking model's hidden reasoning (``CLOUD_REASONING_TOKENS``)."""
    try:
        return max(0, int(os.getenv("CLOUD_REASONING_TOKENS", "0").strip() or 0))
    except ValueError:
        return 0


def log_call(status: str, messages: int, started: float) -> None:
    event = {
        "status": status,
        "messages": messages,
        "latency_ms": round(1000 * (time.perf_counter() - started)),
    }
    logger.info(json.dumps(event))


def error(status: int, message: str) -> JSONResponse:
    # Ollama's error shape: OllamaClient raises ServiceError on any status >= 400.
    return JSONResponse(status_code=status, content={"error": message})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "provider_configured": provider() is not None}


@app.post("/api/chat", response_model=None)
async def chat(request: Request) -> JSONResponse | StreamingResponse:
    started = time.perf_counter()
    try:
        body = await request.json()
    except ValueError:
        return error(400, "invalid json")
    messages = len(body.get("messages") or [])
    cfg = provider()
    if cfg is None:
        log_call("not_configured", messages, started)
        return error(503, "cloud provider not configured")
    payload = to_openai(body, cfg["model"])
    url = cfg["base_url"] + "/chat/completions"
    headers = {"Authorization": "Bearer " + cfg["api_key"]}

    if not payload["stream"]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError:
            log_call("unreachable", messages, started)
            return error(502, "cloud provider unreachable")
        if response.is_error:
            log_call(f"provider_{response.status_code}", messages, started)
            return error(502, f"cloud provider refused the call ({response.status_code})")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            log_call("bad_answer", messages, started)
            return error(502, "cloud provider gave an invalid answer")
        log_call("ok", messages, started)
        return JSONResponse({"message": {"role": "assistant", "content": content}, "done": True})

    async def pieces() -> AsyncIterator[bytes]:
        status = "ok"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.is_error:
                        status = f"provider_{response.status_code}"
                        yield _line(
                            {"error": f"cloud provider refused the call ({response.status_code})"}
                        )
                        return
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0].get("delta") or {}
                        except (ValueError, KeyError, IndexError, TypeError):
                            status = "bad_answer"
                            yield _line({"error": "cloud provider gave an invalid answer"})
                            return
                        if delta.get("content"):
                            yield _line(
                                {
                                    "message": {"role": "assistant", "content": delta["content"]},
                                    "done": False,
                                }
                            )
            yield _line({"message": {"role": "assistant", "content": ""}, "done": True})
        except httpx.HTTPError:
            status = "unreachable"
            yield _line({"error": "cloud provider unreachable"})
        finally:
            log_call(status, messages, started)

    return StreamingResponse(pieces(), media_type="application/x-ndjson")


def _line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
