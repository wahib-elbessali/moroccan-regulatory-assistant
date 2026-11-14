from __future__ import annotations

import app as web_app
import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from src.core.leak.fingerprint import fingerprints

TOKEN = "test-api-token"
KEY = b"test-hmac-key"
REQUEST_ID = "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def api(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config = {
        "web": {
            "enabled": True,
            "max_results": 5,
            "max_query_words": 12,
            "max_snippet_chars": 500,
            "timeout_s": 5,
        },
        "leak": {
            "ngram": 4,
            "min_hits": 1,
            "max_df": 20,
            "overlap_threshold": 0.2,
        },
    }
    config_path.write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        web_app,
        "DATABASE_PATH",
        tmp_path / "leak.sqlite3",
    )
    monkeypatch.setenv("LEAK_API_TOKEN", TOKEN)
    monkeypatch.setenv("LEAK_HMAC_KEY", KEY.decode())
    monkeypatch.setenv("INTERNAL_NETWORK_CIDR", "172.22.0.0/16")

    outgoing_requests = []

    def handler(request):
        outgoing_requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Example result",
                        "content": "A test search result",
                        "extra": "must not be returned",
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(
        web_app.httpx,
        "AsyncClient",
        mock_async_client,
    )

    with TestClient(
        web_app.app,
        client=("172.22.0.10", 50000),
    ) as client:
        yield client, outgoing_requests, config_path


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_requires_token(api):
    client, _, _ = api

    assert client.get("/health").status_code == 401
    assert client.get("/health", headers=auth()).status_code == 200


def test_search_rejects_invalid_token(api):
    client, outgoing, _ = api

    response = client.post(
        "/search",
        json={
            "query": "ordinary search",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert outgoing == []


def test_search_blocks_protected_content(api):
    client, outgoing, _ = api
    query = "secret document contains confidential information"

    grams, refs = fingerprints(query, KEY, 4)

    indexed = client.post(
        "/index",
        json={
            "doc_id": "protected-document",
            "grams": grams,
            "refs": refs,
        },
        headers=auth(),
    )
    assert indexed.status_code == 204

    response = client.post(
        "/search",
        json={
            "query": query,
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "leak_blocked"
    assert response.json()["hits"] >= 1
    assert outgoing == []


def test_search_forwards_allowed_query(api):
    client, outgoing, _ = api

    response = client.post(
        "/search",
        json={
            "query": "weather forecast in Casablanca",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 200
    assert len(outgoing) == 1
    assert outgoing[0].url.params["q"] == "weather forecast in Casablanca"

    results = response.json()["results"]
    assert len(results) == 1
    assert results[0] == {
        "url": "https://example.com",
        "title": "Example result",
        "snippet": "A test search result",
    }


def test_search_refuses_when_web_is_disabled(api):
    client, outgoing, config_path = api

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["web"]["enabled"] = False
    config_path.write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )

    response = client.post(
        "/search",
        json={
            "query": "ordinary search",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 403
    assert response.json() == {"code": "web_disabled"}
    assert outgoing == []


def test_search_rejects_query_over_word_limit(api):
    client, outgoing, _ = api

    response = client.post(
        "/search",
        json={
            "query": "one two three four five six seven eight nine ten eleven twelve thirteen",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_query"
    assert outgoing == []


def test_index_endpoints_require_token(api):
    client, _, _ = api

    payload = {
        "doc_id": "document-1",
        "grams": [],
        "refs": [],
    }

    assert client.post("/index", json=payload).status_code == 401

    assert (
        client.post(
            "/blocking",
            json={"doc_id": "document-1", "blocking": False},
        ).status_code
        == 401
    )

    assert client.delete("/index/document-1").status_code == 401


def test_blocked_query_is_not_logged(api, caplog):
    client, _, _ = api
    query = "secret document contains confidential information"

    grams, refs = fingerprints(query, KEY, 4)

    client.post(
        "/index",
        json={
            "doc_id": "protected-document",
            "grams": grams,
            "refs": refs,
        },
        headers=auth(),
    )

    with caplog.at_level("INFO", logger="web_search"):
        response = client.post(
            "/search",
            json={
                "query": query,
                "max_results": 5,
                "request_id": REQUEST_ID,
            },
            headers=auth(),
        )

    assert response.status_code == 403

    logs = "\n".join(record.message for record in caplog.records)
    assert query not in logs
    assert REQUEST_ID in logs
    assert '"status": "blocked"' in logs


def test_blocking_and_delete_require_token(api):
    client, _, _ = api

    indexed = client.post(
        "/index",
        json={
            "doc_id": "document-2",
            "grams": ["0123456789abcdef"],
            "refs": [],
        },
        headers=auth(),
    )
    assert indexed.status_code == 204

    # Unauthorized requests must be rejected.
    assert (
        client.post(
            "/blocking",
            json={"doc_id": "document-2", "blocking": False},
        ).status_code
        == 401
    )

    assert (
        client.delete(
            "/index/document-2",
        ).status_code
        == 401
    )

    # Authorized requests must succeed.
    blocked = client.post(
        "/blocking",
        json={"doc_id": "document-2", "blocking": False},
        headers=auth(),
    )
    assert blocked.status_code == 204

    assert web_app.app.state.store.get("0123456789abcdef") == [("document-2", False, "gram")]

    deleted = client.delete(
        "/index/document-2",
        headers=auth(),
    )
    assert deleted.status_code == 204

    assert web_app.app.state.store.get("0123456789abcdef") == []


def test_search_filters_invalid_results_and_respects_limit(api, monkeypatch):
    client, _, config_path = api

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["web"]["max_results"] = 2
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    async def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://searxng:8080/search"),
            json={
                "results": [
                    None,
                    {"url": "https://example.com", "title": "Valid", "content": "A" * 600},
                    {"url": 123, "title": "Invalid"},
                    {"url": "https://second.com", "title": "Second", "content": "OK"},
                    {"url": "https://third.com", "title": "Third"},
                ]
            },
        )

    monkeypatch.setattr(
        web_app.app.state.http_client,
        "get",
        fake_get,
    )

    response = client.post(
        "/search",
        json={
            "query": "ordinary search",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["snippet"] == "A" * 500
    assert results[1]["title"] == "Second"


def test_search_handles_upstream_http_error(api, monkeypatch):
    client, outgoing, _ = api

    async def fake_get(*args, **kwargs):
        return httpx.Response(
            503,
            request=httpx.Request("GET", "http://searxng:8080/search"),
        )

    monkeypatch.setattr(
        web_app.app.state.http_client,
        "get",
        fake_get,
    )

    response = client.post(
        "/search",
        json={
            "query": "ordinary search",
            "max_results": 5,
            "request_id": REQUEST_ID,
        },
        headers=auth(),
    )

    assert response.status_code == 503
    assert response.json() == {"code": "search_unavailable"}


def test_search_logs_allowed_query(api, caplog):
    client, _, _ = api
    query = "weather forecast in Casablanca"

    with caplog.at_level("INFO", logger="web_search"):
        response = client.post(
            "/search",
            json={
                "query": query,
                "max_results": 5,
                "request_id": REQUEST_ID,
            },
            headers=auth(),
        )

    assert response.status_code == 200

    logs = "\n".join(record.message for record in caplog.records)
    assert query in logs
    assert REQUEST_ID in logs
    assert '"status": "ok"' in logs


@pytest.mark.asyncio
async def test_rejects_egress_network_with_valid_token(api):
    from fastapi import HTTPException
    from starlette.requests import Request

    client, _, _ = api

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/health",
            "raw_path": b"/health",
            "query_string": b"",
            "headers": [],
            "client": ("172.23.0.10", 50000),
            "server": ("web-search", 8090),
            "app": web_app.app,
        }
    )

    with pytest.raises(HTTPException) as exc:
        await web_app.require_token(
            request,
            authorization=f"Bearer {TOKEN}",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "forbidden_network"}


VALID_FINGERPRINT = "0123456789abcdef"


@pytest.mark.parametrize("field", ["grams", "refs"])
@pytest.mark.parametrize(
    "bad_value",
    [
        "المادة الأولى من القانون",  # raw Arabic text
        "0123456789abcde",  # too short
        "0123456789abcdef0",  # too long
        "0123456789ABCDEF",  # uppercase hex
        "ref: 0123456789abcdef",  # not a bare fingerprint
    ],
)
def test_index_refuses_anything_but_hex_fingerprints(api, field, bad_value):
    client, _, _ = api

    payload = {"doc_id": "document-3", "grams": [], "refs": []}
    payload[field] = [VALID_FINGERPRINT, bad_value]

    response = client.post("/index", json=payload, headers=auth())

    assert response.status_code == 422

    # Nothing is stored, not even the valid fingerprint sent in the same request.
    store = web_app.app.state.store
    assert store.get(bad_value) == []
    assert store.get(VALID_FINGERPRINT) == []
