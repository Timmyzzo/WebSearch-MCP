import json

import httpx
import pytest

from grok_search.clients.tavily import TavilyClient, TavilyClientError
from grok_search.tavily_reliability import (
    TavilyReliabilityManager,
    TavilyServiceState,
    key_fingerprint,
)

KEYS = ("tvly-alpha-1234567890", "tvly-bravo-0987654321")


def bearer_key(request: httpx.Request) -> str:
    return request.headers["authorization"].removeprefix("Bearer ")


def success_response(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/search":
        return httpx.Response(200, json={"results": []})
    if request.url.path == "/extract":
        return httpx.Response(200, json={"results": [{"raw_content": "# Page"}]})
    return httpx.Response(
        200,
        json={"base_url": "https://example.com", "results": [], "response_time": 0.1},
    )


class FakeClock:
    def __init__(self, value: float = 1_000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def test_tavily_search_extract_and_map_use_expected_endpoints():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (request.url.path, request.headers["authorization"], json.loads(request.content))
        )
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Docs",
                            "url": "https://example.com/docs",
                            "content": "Text",
                            "score": 0.9,
                        }
                    ]
                },
            )
        if request.url.path == "/extract":
            return httpx.Response(200, json={"results": [{"raw_content": "# Page"}]})
        return httpx.Response(
            200,
            json={
                "base_url": "https://example.com",
                "results": ["https://example.com/docs"],
                "response_time": 0.2,
            },
        )

    keys = iter(["key-one", "key-two", "key-three"])
    client = TavilyClient(
        "https://api.tavily.com/",
        lambda: next(keys),
        transport=httpx.MockTransport(handler),
    )

    search = await client.search("query", 3)
    extract = await client.extract("https://example.com/docs")
    site_map = await client.map("https://example.com", instructions="docs only")

    assert search[0].url == "https://example.com/docs"
    assert extract == "# Page"
    assert site_map.results == ["https://example.com/docs"]
    assert [item[0] for item in requests] == ["/search", "/extract", "/map"]
    assert [item[1] for item in requests] == [
        "Bearer key-one",
        "Bearer key-two",
        "Bearer key-three",
    ]
    assert requests[2][2]["instructions"] == "docs only"


async def test_search_extract_and_map_share_key_health_state():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        key = bearer_key(request)
        requests.append((request.url.path, key))
        if key == KEYS[0]:
            return httpx.Response(401, json={"error": "invalid API key"})
        return success_response(request)

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    await client.search("query")
    await client.extract("https://example.com")
    await client.map("https://example.com")

    assert requests == [
        ("/search", KEYS[0]),
        ("/search", KEYS[1]),
        ("/extract", KEYS[1]),
        ("/map", KEYS[1]),
    ]
    statuses = await client.reliability.status_summary()
    assert statuses[0]["state"] == "invalid"
    await client.aclose()


@pytest.mark.parametrize("status", [401, 403])
async def test_401_and_403_disable_key_and_try_the_next_key(status):
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        if len(seen) == 1:
            return httpx.Response(status, json={"error": {"message": "authentication failed"}})
        return success_response(request)

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    assert await client.search("query") == []

    assert seen == list(KEYS)
    statuses = await client.reliability.status_summary()
    assert statuses[0]["state"] == "invalid"
    assert statuses[1]["state"] == "healthy"
    await client.aclose()


@pytest.mark.parametrize(
    ("body", "expected_state"),
    [
        ({"error": {"code": "rate_limited", "message": "try again later"}}, "cooldown"),
        (
            {"error": {"code": "quota_exceeded", "message": "monthly quota exhausted"}},
            "quota_exhausted",
        ),
    ],
)
async def test_429_distinguishes_temporary_rate_limit_from_quota_exhaustion(
    body, expected_state
):
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "45"}, json=body)
        return success_response(request)

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    await client.search("query")

    statuses = await client.reliability.status_summary()
    assert seen == list(KEYS)
    assert statuses[0]["state"] == expected_state
    assert 44 <= statuses[0]["retry_after_seconds"] <= 45
    await client.aclose()


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
async def test_temporary_http_failures_try_next_key_without_permanent_invalidation(status):
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        if len(seen) == 1:
            return httpx.Response(status, json={"error": {"message": "temporary outage"}})
        return success_response(request)

    client = TavilyClient(
        "https://api.tavily.com",
        KEYS,
        transport=httpx.MockTransport(handler),
        service_failure_threshold=3,
    )

    await client.search("query")

    statuses = await client.reliability.status_summary()
    assert seen == list(KEYS)
    assert statuses[0]["state"] == "cooldown"
    assert statuses[1]["state"] == "healthy"
    await client.aclose()


@pytest.mark.parametrize("failure", ["connect", "timeout"])
async def test_network_and_timeout_failures_try_next_key_without_invalidating(failure):
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        if len(seen) == 1:
            if failure == "connect":
                raise httpx.ConnectError("connection failed", request=request)
            raise httpx.ReadTimeout("read timed out", request=request)
        return success_response(request)

    client = TavilyClient(
        "https://api.tavily.com",
        KEYS,
        transport=httpx.MockTransport(handler),
        service_failure_threshold=3,
    )

    await client.search("query")

    statuses = await client.reliability.status_summary()
    assert seen == list(KEYS)
    assert statuses[0]["state"] == "cooldown"
    assert statuses[1]["state"] == "healthy"
    await client.aclose()


@pytest.mark.parametrize("status", [400, 422])
async def test_request_validation_errors_do_not_rotate_through_keys(status):
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        return httpx.Response(status, json={"error": {"message": "invalid parameter"}})

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    with pytest.raises(TavilyClientError) as caught:
        await client.search("query")

    assert caught.value.code == "tavily_request_invalid"
    assert seen == [KEYS[0]]
    assert all(item["state"] == "healthy" for item in await client.reliability.status_summary())
    await client.aclose()


async def test_404_returns_api_configuration_error_without_rotating_keys():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        return httpx.Response(404, text="route not found")

    client = TavilyClient("https://api.tavily.com/v0", KEYS, transport=httpx.MockTransport(handler))

    with pytest.raises(TavilyClientError) as caught:
        await client.search("query")

    assert caught.value.code == "tavily_api_configuration_error"
    assert "TAVILY_API_URL" in caught.value.message
    assert seen == [KEYS[0]]
    await client.aclose()


async def test_all_keys_returning_same_endpoint_error_reports_configuration_problem():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(bearer_key(request))
        return httpx.Response(
            405,
            json={"error": {"code": "unsupported_route", "message": "wrong API version"}},
        )

    client = TavilyClient("https://api.tavily.com/v0", KEYS, transport=httpx.MockTransport(handler))

    with pytest.raises(TavilyClientError) as caught:
        await client.search("query")

    assert caught.value.code == "tavily_api_configuration_error"
    assert "TAVILY_API_URL" in caught.value.message
    assert seen == list(KEYS)
    await client.aclose()


async def test_all_keys_unavailable_returns_stable_masked_diagnostics():
    async def handler(request: httpx.Request) -> httpx.Response:
        key = bearer_key(request)
        return httpx.Response(401, json={"error": {"message": f"revoked key {key}"}})

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    with pytest.raises(TavilyClientError) as caught:
        await client.extract("https://example.com")

    error = caught.value
    serialized = json.dumps(error.to_dict(), ensure_ascii=False)
    assert error.code == "tavily_all_keys_unavailable"
    assert {item["state"] for item in error.key_statuses} == {"invalid"}
    assert {item["fingerprint"] for item in error.key_statuses} == {
        key_fingerprint(key) for key in KEYS
    }
    assert "补充有效 Key" in error.message
    assert all(key not in serialized for key in KEYS)
    await client.aclose()


async def test_service_circuit_fast_fails_without_additional_http_requests():
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(503, text="maintenance")

    client = TavilyClient(
        "https://api.tavily.com",
        KEYS,
        transport=httpx.MockTransport(handler),
        key_cooldown=0,
        service_failure_threshold=2,
        service_cooldown=60,
    )

    with pytest.raises(TavilyClientError) as first:
        await client.search("query")
    assert first.value.code == "tavily_service_unavailable"
    assert request_count == 2

    with pytest.raises(TavilyClientError) as second:
        await client.search("query again")
    assert second.value.code == "tavily_service_unavailable"
    assert request_count == 2
    await client.aclose()


async def test_half_open_probe_success_restores_client_requests():
    clock = FakeClock()
    manager = TavilyReliabilityManager(
        KEYS,
        key_cooldown=0,
        service_failure_threshold=2,
        service_cooldown=10,
        clock=clock,
    )
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count <= 2:
            return httpx.Response(503, text="maintenance")
        return success_response(request)

    client = TavilyClient(
        "https://api.tavily.com",
        KEYS,
        transport=httpx.MockTransport(handler),
        reliability_manager=manager,
    )
    with pytest.raises(TavilyClientError):
        await client.search("opens circuit")
    clock.advance(10)

    assert await client.search("half-open probe") == []

    assert request_count == 3
    assert manager.service_state is TavilyServiceState.CLOSED
    await client.aclose()


async def test_async_client_and_connection_pool_are_reused_until_explicit_close():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return success_response(request)

    client = TavilyClient("https://api.tavily.com", KEYS, transport=httpx.MockTransport(handler))

    await client.search("query")
    pooled_client = client._client
    await client.extract("https://example.com")
    await client.map("https://example.com")

    assert pooled_client is not None
    assert client._client is pooled_client
    assert not pooled_client.is_closed
    assert requests == ["/search", "/extract", "/map"]

    await client.aclose()
    assert pooled_client.is_closed
    with pytest.raises(TavilyClientError) as caught:
        await client.search("after close")
    assert caught.value.code == "tavily_client_closed"
