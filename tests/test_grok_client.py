import json

import httpx

from grok_search.clients.grok import GrokClient


async def test_grok_search_parses_openai_compatible_sse(monkeypatch):
    monkeypatch.setenv("GROK_RETRY_MAX_ATTEMPTS", "0")
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        body = (
            'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
            'data:{"choices":[{"delta":{"content":"world"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = GrokClient(
        "https://grok.example/v1/",
        "secret",
        "grok-test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("current release")

    assert result == "hello world"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["model"] == "grok-test"
    assert captured["payload"]["stream"] is True


async def test_grok_list_models_filters_invalid_items():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"name": "missing"}, {"id": "b"}]})

    client = GrokClient(
        "https://grok.example/v1",
        "secret",
        "grok-test",
        transport=httpx.MockTransport(handler),
    )

    assert await client.list_models() == ["a", "b"]
