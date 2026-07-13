import asyncio
import json
from contextlib import suppress

import httpx
import pytest

from grok_search.budget import RequestBudget
from grok_search.clients.grok import GrokClient, GrokClientError
from grok_search.clients.tavily import TavilyClient, TavilyClientError
from grok_search.concurrency import AsyncConcurrencyLimiter
from grok_search.tools import web as web_tools


def sse(content: str = "ok") -> httpx.Response:
    body = f'data: {json.dumps({"choices": [{"delta": {"content": content}}]})}\n\n'
    body += "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def grok_error_response(status: int = 503) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": "upstream_unavailable", "message": "temporary"}},
    )


def tavily_success(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/extract":
        return httpx.Response(200, json={"results": [{"raw_content": "# Page"}]})
    if request.url.path == "/map":
        return httpx.Response(
            200,
            json={"base_url": "https://example.com", "results": ["https://example.com/a"]},
        )
    return httpx.Response(200, json={"results": []})


async def no_sleep(_: float) -> None:
    return None


async def test_grok_process_limiter_never_exceeds_two_http_requests():
    limiter = AsyncConcurrencyLimiter(2)
    release = asyncio.Event()
    two_entered = asyncio.Event()
    active = 0
    maximum = 0
    entered = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum, entered
        active += 1
        entered += 1
        maximum = max(maximum, active)
        if entered >= 2:
            two_entered.set()
        try:
            await release.wait()
            return sse()
        finally:
            active -= 1

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        concurrency_limiter=limiter,
    )
    tasks = [
        asyncio.create_task(
            client.search(
                f"q-{index}",
                primary_model="primary",
                max_attempts=1,
                budget=RequestBudget(2),
            )
        )
        for index in range(3)
    ]
    await asyncio.wait_for(two_entered.wait(), 1)
    await asyncio.sleep(0.02)
    assert maximum == 2
    assert limiter.active == 2

    release.set()
    assert await asyncio.gather(*tasks) == ["ok", "ok", "ok"]
    assert limiter.active == 0
    await client.aclose()


async def test_grok_retries_still_obey_the_shared_concurrency_limit():
    limiter = AsyncConcurrencyLimiter(2)
    active = 0
    maximum = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.02)
            return grok_error_response()
        finally:
            active -= 1

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        concurrency_limiter=limiter,
        sleep=no_sleep,
    )
    outcomes = await asyncio.gather(
        *(
            client.search(
                f"q-{index}",
                primary_model="primary",
                max_attempts=2,
                budget=RequestBudget(5),
            )
            for index in range(3)
        ),
        return_exceptions=True,
    )

    assert maximum == 2
    assert limiter.active == 0
    assert all(isinstance(outcome, GrokClientError) for outcome in outcomes)
    assert all(outcome.actual_attempts == 2 for outcome in outcomes)
    await client.aclose()


async def test_grok_queue_wait_counts_toward_budget_and_releases_after_cancellation():
    limiter = AsyncConcurrencyLimiter(1)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return sse()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        concurrency_limiter=limiter,
    )
    first = asyncio.create_task(
        client.search(
            "first",
            primary_model="primary",
            max_attempts=1,
            budget=RequestBudget(2),
        )
    )
    await entered.wait()

    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "queued",
            primary_model="primary",
            max_attempts=1,
            budget=RequestBudget(0.05),
        )
    assert caught.value.termination_reason == "concurrency_queue_timeout"
    assert caught.value.actual_attempts == 0
    assert caught.value.queue_wait_ms > 0
    assert "等待上游并发槽位" in caught.value.message

    first.cancel()
    with suppress(asyncio.CancelledError):
        await first
    assert limiter.active == 0
    release.set()
    assert await client.search(
        "after cancellation",
        primary_model="primary",
        max_attempts=1,
        budget=RequestBudget(1),
    ) == "ok"
    await client.aclose()


async def test_grok_failure_messages_match_the_actual_termination_reason():
    async def fatal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "invalid_api_key", "message": "incorrect api key"}},
        )

    fatal = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(fatal_handler),
    )
    with pytest.raises(GrokClientError) as stopped:
        await fatal.search("q", primary_model="primary", max_attempts=5)
    assert stopped.value.actual_attempts == 1
    assert stopped.value.configured_max_attempts == 5
    assert stopped.value.termination_reason == "non_retryable_error"
    assert "不可重试错误提前停止" in stopped.value.message

    exhausted = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(lambda request: grok_error_response()),
        sleep=no_sleep,
    )
    with pytest.raises(GrokClientError) as used_all:
        await exhausted.search("q", primary_model="primary", max_attempts=2)
    assert used_all.value.actual_attempts == 2
    assert used_all.value.termination_reason == "max_attempts_exhausted"
    assert "已用尽最大尝试次数" in used_all.value.message
    await fatal.aclose()
    await exhausted.aclose()


async def test_grok_does_not_start_a_retry_that_cannot_fit_remaining_budget():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return grok_error_response()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        random_source=lambda: 0.0,
    )
    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q",
            primary_model="primary",
            max_attempts=5,
            budget=RequestBudget(0.2),
        )
    assert calls == 1
    assert caught.value.actual_attempts == 1
    assert caught.value.termination_reason == "total_budget_exhausted"
    assert "搜索总时间预算已耗尽" in caught.value.message
    await client.aclose()


async def test_grok_retry_after_is_not_slept_when_it_would_break_total_budget():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "5"},
            json={"error": {"code": "rate_limited", "message": "busy"}},
        )

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q",
            primary_model="primary",
            max_attempts=5,
            budget=RequestBudget(0.2),
        )
    assert calls == 1
    assert caught.value.termination_reason == "total_budget_exhausted"
    assert caught.value.last_http_status == 429
    await client.aclose()


async def test_tavily_same_key_is_serial_but_distinct_keys_run_concurrently():
    per_key_active: dict[str, int] = {}
    per_key_maximum: dict[str, int] = {}
    total_active = 0
    total_maximum = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal total_active, total_maximum
        key = request.headers["authorization"].removeprefix("Bearer ")
        per_key_active[key] = per_key_active.get(key, 0) + 1
        per_key_maximum[key] = max(per_key_maximum.get(key, 0), per_key_active[key])
        total_active += 1
        total_maximum = max(total_maximum, total_active)
        try:
            await asyncio.sleep(0.04)
            return tavily_success(request)
        finally:
            per_key_active[key] -= 1
            total_active -= 1

    one_key = TavilyClient(
        "https://api.tavily.com",
        ["tvly-only-key-0001"],
        transport=httpx.MockTransport(handler),
    )
    await asyncio.gather(
        one_key.search("q"),
        one_key.extract("https://example.com"),
        one_key.map("https://example.com"),
    )
    assert per_key_maximum["tvly-only-key-0001"] == 1
    await one_key.aclose()

    per_key_active.clear()
    per_key_maximum.clear()
    total_active = 0
    total_maximum = 0
    two_keys = TavilyClient(
        "https://api.tavily.com",
        ["tvly-key-alpha-0001", "tvly-key-bravo-0002"],
        transport=httpx.MockTransport(handler),
    )
    await asyncio.gather(two_keys.search("one"), two_keys.search("two"))
    assert total_maximum == 2
    assert set(per_key_maximum) == {"tvly-key-alpha-0001", "tvly-key-bravo-0002"}
    assert all(value == 1 for value in per_key_maximum.values())
    await two_keys.aclose()


async def test_tavily_busy_key_waits_without_changing_health_and_budget_can_expire():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    client: TavilyClient

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return tavily_success(request)

    client = TavilyClient(
        "https://api.tavily.com",
        ["tvly-only-key-0001"],
        transport=httpx.MockTransport(handler),
    )
    first = asyncio.create_task(
        client.search("first", budget=RequestBudget(2))
    )
    await entered.wait()
    summary = await client.reliability.status_summary()
    assert summary[0]["state"] == "healthy"
    assert summary[0]["in_flight"] == 1

    with pytest.raises(TavilyClientError) as caught:
        await client.search("queued", budget=RequestBudget(0.05))
    assert caught.value.code == "tavily_concurrency_timeout"
    assert caught.value.diagnostics["termination_reason"] == "concurrency_queue_timeout"
    summary = await client.reliability.status_summary()
    assert summary[0]["state"] == "healthy"
    assert summary[0]["in_flight"] == 1

    release.set()
    assert await first == []
    assert (await client.reliability.status_summary())[0]["in_flight"] == 0
    await client.aclose()


async def test_tavily_slots_release_after_cancellation_exception_and_circuit_open():
    entered = asyncio.Event()
    blocker = asyncio.Event()
    calls = 0

    async def cancel_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await blocker.wait()
        return tavily_success(request)

    client = TavilyClient(
        "https://api.tavily.com",
        ["tvly-only-key-0001"],
        transport=httpx.MockTransport(cancel_handler),
    )
    task = asyncio.create_task(client.search("cancel", budget=RequestBudget(2)))
    await entered.wait()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert (await client.reliability.status_summary())[0]["in_flight"] == 0
    assert await client.search("after cancel") == []
    await client.aclose()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return tavily_success(request)

    timed_out = TavilyClient(
        "https://api.tavily.com",
        ["tvly-only-key-0001"],
        transport=httpx.MockTransport(slow_handler),
    )
    with pytest.raises(TavilyClientError) as budget_error:
        await timed_out.search("slow", budget=RequestBudget(0.05))
    assert budget_error.value.code == "tavily_total_budget_exhausted"
    timeout_status = (await timed_out.reliability.status_summary())[0]
    assert timeout_status["state"] == "healthy"
    assert timeout_status["in_flight"] == 0
    await timed_out.aclose()

    failure_calls = 0

    async def failure_handler(request: httpx.Request) -> httpx.Response:
        nonlocal failure_calls
        failure_calls += 1
        if failure_calls == 1:
            raise httpx.ConnectError("offline", request=request)
        return tavily_success(request)

    failed = TavilyClient(
        "https://api.tavily.com",
        ["tvly-only-key-0001"],
        transport=httpx.MockTransport(failure_handler),
        key_cooldown=0,
    )
    with pytest.raises(TavilyClientError):
        await failed.search("fails")
    assert (await failed.reliability.status_summary())[0]["in_flight"] == 0
    assert await failed.search("recovers") == []
    await failed.aclose()

    async def outage_handler(request: httpx.Request) -> httpx.Response:
        return grok_error_response()

    circuit = TavilyClient(
        "https://api.tavily.com",
        ["tvly-key-alpha-0001", "tvly-key-bravo-0002"],
        transport=httpx.MockTransport(outage_handler),
        key_cooldown=0,
        service_failure_threshold=2,
    )
    with pytest.raises(TavilyClientError) as opened:
        await circuit.search("outage")
    assert opened.value.code == "tavily_service_unavailable"
    assert all(item["in_flight"] == 0 for item in await circuit.reliability.status_summary())
    await circuit.aclose()


async def test_web_search_total_budget_returns_structured_error_and_does_not_cache(monkeypatch):
    class SlowGrok:
        async def search(self, query, platform="", **kwargs):
            await asyncio.sleep(1)
            return "late answer"

        async def aclose(self):
            return None

    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "primary")
    monkeypatch.setenv("WEB_SEARCH_TOTAL_TIMEOUT", "0.05")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: SlowGrok())

    result = await web_tools.web_search("timeout")

    assert result.status == "error"
    assert result.error == "grok_total_budget_exhausted"
    assert result.grok_error.termination_reason == "total_budget_exhausted"
    assert result.grok_error.actual_attempts == 0
    assert result.error_detail.diagnostics["budget_ms"] == 50
    assert await web_tools._SOURCES_CACHE.get(result.session_id) is None


async def test_concurrent_web_search_sources_and_diagnostics_remain_isolated(monkeypatch):
    class PerQueryGrok:
        async def search(self, query, platform="", **kwargs):
            if query == "bad":
                raise GrokClientError(
                    code="grok_request_invalid",
                    message="Grok 请求参数无效，因不可重试错误提前停止",
                    primary_model="primary",
                    fallback_model=None,
                    primary_attempts=1,
                    fallback_attempts=0,
                    last_failure=_fatal_failure(),
                    switched_model=False,
                    termination_reason="non_retryable_error",
                    configured_max_attempts=5,
                    budget=kwargs["budget"],
                )
            return f"Answer {query}\n\nSources:\n- [{query}](https://example.com/{query})"

        async def aclose(self):
            return None

    def _fatal_failure():
        from grok_search.clients.grok import _AttemptFailure

        return _AttemptFailure("request_invalid", action="fatal", http_status=400)

    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "primary")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: PerQueryGrok())

    first, second, failed = await asyncio.gather(
        web_tools.web_search("first"),
        web_tools.web_search("second"),
        web_tools.web_search("bad"),
    )
    first_sources, second_sources = await asyncio.gather(
        web_tools.get_sources(first.session_id),
        web_tools.get_sources(second.session_id),
    )

    assert first.session_id != second.session_id != failed.session_id
    assert first_sources.sources[0].url == "https://example.com/first"
    assert second_sources.sources[0].url == "https://example.com/second"
    assert failed.grok_error.actual_attempts == 1
    assert failed.grok_error.termination_reason == "non_retryable_error"
    assert await web_tools._SOURCES_CACHE.get(failed.session_id) is None
