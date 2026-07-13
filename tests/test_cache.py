from grok_search.sources import SourcesCache
from grok_search.tools import web as web_tools


async def test_sources_cache_expires_sessions_and_keeps_lru_bound():
    now = [0.0]
    cache = SourcesCache(max_size=2, ttl_seconds=10.0, clock=lambda: now[0])

    await cache.set("one", [{"url": "https://example.com/one"}])
    now[0] = 5.0
    assert await cache.get("one") == [{"url": "https://example.com/one"}]

    await cache.set("two", [])
    await cache.set("three", [])
    assert await cache.get("one") is None

    now[0] = 15.0
    assert await cache.get("two") is None
    assert await cache.get("three") is None


async def test_model_catalog_cache_refreshes_after_ttl(monkeypatch):
    now = [0.0]

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def list_models(self):
            self.calls += 1
            return [f"model-{self.calls}"]

    client = FakeClient()

    async def fake_get_client(api_url, api_key):
        return client

    monkeypatch.setattr(web_tools, "_get_grok_client", fake_get_client)
    monkeypatch.setattr(web_tools, "_AVAILABLE_MODELS_CACHE_TTL", 10.0)
    monkeypatch.setattr(web_tools.time, "monotonic", lambda: now[0])

    assert await web_tools._get_available_models_cached("https://example.com/v1", "key") == [
        "model-1"
    ]
    now[0] = 9.0
    assert await web_tools._get_available_models_cached("https://example.com/v1", "key") == [
        "model-1"
    ]
    now[0] = 10.0
    assert await web_tools._get_available_models_cached("https://example.com/v1", "key") == [
        "model-2"
    ]
    assert client.calls == 2
