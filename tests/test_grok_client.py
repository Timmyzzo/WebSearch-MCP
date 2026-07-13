import asyncio
import json

import httpx
import pytest

from grok_search.clients.grok import GrokClient, GrokClientError


def sse(content: str = "ok") -> httpx.Response:
    body = f'data: {json.dumps({"choices": [{"delta": {"content": content}}]})}\n\n'
    body += "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def error_response(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


class InterruptingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        raise httpx.RemoteProtocolError("stream interrupted")

    async def aclose(self):
        self.closed = True


async def test_grok_search_only_uses_chat_completions(monkeypatch):
    captured = {}
    monkeypatch.setenv("GROK_API_PROTOCOL", "responses")

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return sse("hello world")

    client = GrokClient(
        "https://grok.example/v1/",
        "secret",
        "grok-test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("current release", max_attempts=1)

    assert result == "hello world"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["model"] == "grok-test"
    assert captured["payload"]["stream"] is True
    await client.aclose()


async def test_grok_list_models_filters_invalid_items():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"name": "x"}, {"id": "b"}]})

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    assert await client.list_models() == ["a", "b"]
    await client.aclose()


async def test_primary_retries_then_succeeds_without_real_sleep():
    models = []
    sleeps = []

    async def handler(request: httpx.Request) -> httpx.Response:
        models.append(json.loads(request.content)["model"])
        return error_response(503, "overloaded", "service busy") if len(models) == 1 else sse()

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        random_source=lambda: 0.0,
    )

    assert await client.search("q", primary_model="primary", max_attempts=3) == "ok"
    assert models == ["primary", "primary"]
    assert sleeps == [0.5]


async def test_deprecated_fallback_argument_is_ignored():
    models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        return error_response(503, "upstream_unavailable", "try later")

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )

    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q", primary_model="primary", fallback_model="fallback", max_attempts=2
        )

    assert models == ["primary", "primary"]
    assert caught.value.fallback_model is None
    assert caught.value.fallback_attempts == 0
    assert caught.value.switched_model is False


async def _completed_sleep() -> None:
    return None


async def test_single_model_fails_with_exact_attempt_count():
    async def handler(request: httpx.Request) -> httpx.Response:
        return error_response(429, "rate_limit", "busy")

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )

    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q", primary_model="primary", fallback_model="fallback", max_attempts=3
        )

    error = caught.value
    assert error.code == "grok_primary_failed"
    assert error.primary_attempts == 3
    assert error.fallback_attempts == 0
    assert error.total_attempts == 3
    assert error.switched_model is False
    assert error.last_http_status == 429
    assert error.last_upstream_code == "rate_limit"


async def test_default_single_model_retry_budget_is_five_real_requests(monkeypatch):
    monkeypatch.delenv("GROK_MODEL_MAX_ATTEMPTS", raising=False)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(503, "upstream_unavailable", "try later")

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        "strong-model",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )

    with pytest.raises(GrokClientError) as caught:
        await client.search("q")

    assert calls == 5
    assert caught.value.primary_attempts == 5
    assert caught.value.total_attempts == 5


async def test_no_fallback_and_same_fallback_only_run_one_attempt_group():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(503, "busy", "busy")

    for fallback in (None, "primary"):
        calls = 0
        client = GrokClient(
            "https://grok.example/v1",
            "secret",
            transport=httpx.MockTransport(handler),
            sleep=lambda _: _completed_sleep(),
        )
        with pytest.raises(GrokClientError) as caught:
            await client.search(
                "q", primary_model="primary", fallback_model=fallback, max_attempts=2
            )
        assert calls == 2
        assert caught.value.fallback_model is None
        assert caught.value.fallback_attempts == 0
        assert caught.value.switched_model is False
        assert caught.value.code == "grok_primary_failed"


@pytest.mark.parametrize("status", [408, 429, 500, 501, 502, 503, 504])
async def test_retryable_http_statuses_retry(status):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(status, "temporary", "temporary") if calls == 1 else sse()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )
    assert await client.search("q", primary_model="primary", max_attempts=2) == "ok"
    assert calls == 2


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ConnectError("connect"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.PoolTimeout("pool timeout"),
    ],
)
async def test_network_and_timeout_failures_retry(exception):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise exception
        return sse()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )
    assert await client.search("q", primary_model="primary", max_attempts=2) == "ok"
    assert calls == 2


async def test_relay_account_unavailable_retries_same_model():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return error_response(401, "relay_error", "上游账号不可用，请重新路由")
        return sse()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )
    assert await client.search("q", primary_model="primary", max_attempts=2) == "ok"
    assert calls == 2


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (404, "model_not_found", "model does not exist"),
        (403, "model_access_denied", "does not have access to model"),
        (503, "model_unavailable", "model temporarily unavailable"),
    ],
)
async def test_invalid_model_errors_stop_without_fallback(status, code, message):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(status, code, message)

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GrokClientError):
        await client.search(
            "q", primary_model="primary", fallback_model="fallback", max_attempts=3
        )
    expected_calls = 3 if code == "model_unavailable" else 1
    assert calls == expected_calls


@pytest.mark.parametrize("status", [400, 422])
async def test_parameter_errors_do_not_retry_or_switch(status):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(status, "invalid_request", "bad parameter")

    client = GrokClient("https://grok.example/v1", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q", primary_model="primary", fallback_model="fallback", max_attempts=3
        )
    assert calls == 1
    assert caught.value.code == "grok_request_invalid"
    assert caught.value.switched_model is False


@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_errors_do_not_retry_or_switch(status):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(status, "invalid_api_key", "incorrect api key")

    client = GrokClient("https://grok.example/v1", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(GrokClientError) as caught:
        await client.search(
            "q", primary_model="primary", fallback_model="fallback", max_attempts=3
        )
    assert calls == 1
    assert caught.value.code == "grok_authentication_error"
    assert caught.value.switched_model is False


async def test_stream_interruption_without_content_retries_and_closes_stream():
    calls = 0
    broken = InterruptingStream([])

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, stream=broken, headers={"content-type": "text/event-stream"})
        return sse()

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )
    assert await client.search("q", primary_model="primary", max_attempts=2) == "ok"
    assert calls == 2
    assert broken.closed is True


async def test_partial_stream_interruption_is_never_returned_as_success():
    partial = InterruptingStream(
        [b'data: {"choices":[{"delta":{"content":"partial secret"}}]}\n\n']
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=partial, headers={"content-type": "text/event-stream"})

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GrokClientError) as caught:
        await client.search("q", primary_model="primary", max_attempts=1)
    assert caught.value.last_error_type == "stream_interrupted_after_content"
    assert "partial secret" not in str(caught.value.to_dict())
    assert partial.closed is True
    assert client._concurrency_limiter.active == 0


async def test_finish_reason_marks_content_complete_before_socket_close():
    completed = InterruptingStream(
        [
            b'data: {"choices":[{"delta":{"content":"complete"},'
            b'"finish_reason":"stop"}]}\n\n'
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=completed, headers={"content-type": "text/event-stream"})

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    assert await client.search("q", primary_model="primary", max_attempts=1) == "complete"
    assert completed.closed is True


async def test_backoff_is_exponential_jittered_and_injectable(monkeypatch):
    monkeypatch.setenv("GROK_RETRY_MULTIPLIER", "2")
    monkeypatch.setenv("GROK_RETRY_MAX_WAIT", "10")
    sleeps = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return error_response(503, "busy", "busy")

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        random_source=lambda: 0.5,
    )
    with pytest.raises(GrokClientError):
        await client.search("q", primary_model="primary", max_attempts=3)
    assert sleeps == [1.5, 3.0]


async def test_client_reuses_pool_closes_and_redacts_credentials():
    raw_key = "sk-super-secret-value"
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return error_response(503, raw_key, f"Authorization: Bearer {raw_key}")

    client = GrokClient(
        "https://grok.example/v1",
        raw_key,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: _completed_sleep(),
    )
    http_client = await client._get_client()
    with pytest.raises(GrokClientError) as caught:
        await client.search("q", primary_model="primary", max_attempts=2)
    assert await client._get_client() is http_client
    assert calls == 2
    assert raw_key not in str(caught.value.to_dict())
    assert "Authorization" not in str(caught.value.to_dict())
    await client.aclose()
    assert http_client.is_closed is True


async def test_concurrent_searches_keep_attempt_state_isolated():
    async def handler(request: httpx.Request) -> httpx.Response:
        return error_response(503, "busy", "busy")

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    outcomes = await asyncio.gather(
        client.search("first", primary_model="p", fallback_model="f", max_attempts=1),
        client.search("second", primary_model="p", fallback_model="f", max_attempts=1),
        return_exceptions=True,
    )

    assert all(isinstance(outcome, GrokClientError) for outcome in outcomes)
    assert [(outcome.primary_attempts, outcome.fallback_attempts) for outcome in outcomes] == [
        (1, 0),
        (1, 0),
    ]
