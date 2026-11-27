import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI(title="Cloud LLM Gateway")


def provider_config() -> tuple[str, str, str]:
    base_url = os.getenv("CLOUD_API_BASE", "").strip().rstrip("/")
    api_key = os.getenv("CLOUD_API_KEY", "").strip()
    model = os.getenv("CLOUD_MODEL", "").strip()

    if not base_url or not api_key or not model:
        raise HTTPException(
            status_code=503,
            detail="Cloud provider is not configured",
        )

    return base_url, api_key, model


def provider_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any]):
    base_url, api_key, model = provider_config()

    forwarded_payload = dict(payload)
    forwarded_payload["model"] = model

    url = f"{base_url}/chat/completions"
    headers = provider_headers(api_key)

    try:
        if forwarded_payload.get("stream") is True:
            # Keep the client alive until the stream has been consumed.
            client = httpx.AsyncClient(timeout=120.0)

            try:
                request = client.build_request(
                    "POST",
                    url,
                    json=forwarded_payload,
                    headers=headers,
                )
                response = await client.send(request, stream=True)
            except BaseException:
                await client.aclose()
                raise

            if response.status_code >= 400:
                await response.aclose()
                await client.aclose()
                raise HTTPException(
                    status_code=502,
                    detail="Cloud provider request failed",
                )

            async def forward_stream():
                try:
                    async for chunk in response.aiter_raw():
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                forward_stream(),
                status_code=response.status_code,
                media_type="text/event-stream",
            )

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                json=forwarded_payload,
                headers=headers,
            )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail="Cloud provider request failed",
            )

        return response.json()

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Cloud provider timeout")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Cloud provider unavailable")
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid provider response")

@app.post("/count_tokens")
async def count_tokens(payload: dict[str, Any]) -> dict[str, int]:
    base_url, api_key, model = provider_config()

    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="A text field is required")

    # Gemini exposes token counting through its native API.
    parsed = urlsplit(base_url)
    if parsed.hostname not in {
        "generativelanguage.googleapis.com",
    }:
        raise HTTPException(
            status_code=501,
            detail="Token counting is not implemented for this provider",
        )

    api_root = f"{parsed.scheme}://{parsed.netloc}"
    version = "v1beta"
    count_url = f"{api_root}/{version}/models/{model}:countTokens"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                count_url,
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": text}]}]},
            )

            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail="Cloud token counting failed",
                )

            result = response.json()
            count = result.get("totalTokens")

            if not isinstance(count, int):
                raise HTTPException(
                    status_code=502,
                    detail="Invalid token count response",
                )

            return {"count": count}

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Cloud provider timeout")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Cloud provider unavailable")
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid provider response")
