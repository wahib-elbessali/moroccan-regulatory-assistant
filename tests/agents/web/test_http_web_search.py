import httpx
import pytest

from src.agents.web import HttpWebSearch
from src.core.contracts.errors import LeakBlocked, ServiceError


def make_client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://web-search:8090",
    )


def test_http_search_success_sends_token_and_payload():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/search"
        assert request.headers["Authorization"] == "Bearer test-token"

        import json
        payload = json.loads(request.content)
        assert payload["query"] == "droit fiscal"
        assert payload["max_results"] == 3
        assert payload["request_id"] == "00000000-0000-0000-0000-000000000001"

        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Source fiscale",
                        "snippet": "Résultat de recherche",
                    }
                ]
            },
        )

    client = make_client(handler)
    service = HttpWebSearch(token="test-token", client=client)

    from uuid import UUID
    results = service.search(
        "droit fiscal",
        max_results=3,
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert len(results) == 1
    assert results[0].title == "Source fiscale"
    assert results[0].url == "https://example.com"


def test_http_search_raises_leak_blocked():
    def handler(request):
        return httpx.Response(403, json={"code": "leak_blocked", "hits": 5})

    service = HttpWebSearch(
        token="test-token",
        client=make_client(handler),
    )

    with pytest.raises(LeakBlocked) as exc:
        service.search("requête protégée")

    assert exc.value.hits == 5


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"code": "web_disabled"}),
        httpx.Response(500, json={"detail": "internal error"}),
        httpx.Response(429, json={"detail": "rate limited"}),
    ],
)
def test_http_search_maps_http_errors_to_service_error(response):
    service = HttpWebSearch(
        token="test-token",
        client=make_client(lambda request: response),
    )

    with pytest.raises(ServiceError):
        service.search("droit fiscal")


def test_http_search_maps_transport_error_to_service_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    service = HttpWebSearch(
        token="test-token",
        client=make_client(handler),
    )

    with pytest.raises(ServiceError):
        service.search("droit fiscal")


@pytest.mark.parametrize(
    "body",
    [
        {"invalid": "shape"},
        {"results": "not-a-list"},
        {"results": [{"url": "missing-fields"}]},
        [],
    ],
)
def test_http_search_rejects_invalid_response(body):
    service = HttpWebSearch(
        token="test-token",
        client=make_client(lambda request: httpx.Response(200, json=body)),
    )

    with pytest.raises(ServiceError):
        service.search("droit fiscal")


def test_http_search_requires_token():
    with pytest.raises(ServiceError):
        HttpWebSearch(token="")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"code": "leak_blocked", "hits": "invalid"},
        {"code": "leak_blocked", "hits": -1},
    ],
)
def test_http_search_rejects_malformed_403_response(body):
    service = HttpWebSearch(
        token="test-token",
        client=make_client(
            lambda request: httpx.Response(403, json=body)
        ),
    )

    with pytest.raises(ServiceError):
        service.search("droit fiscal")
