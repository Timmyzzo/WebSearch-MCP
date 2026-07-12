from grok_search.clients.tavily import TavilyClientError
from grok_search.models import TavilyMapResult, TavilySearchResult
from grok_search.tools import web as web_tools


class FakeGrokClient:
    async def search(self, query, platform=""):
        return "Answer\n\nSources:\n- [Official](https://example.com/official)"


class FailingGrokClient:
    async def search(self, query, platform=""):
        raise RuntimeError("grok unavailable")


class FakeTavilyClient:
    async def search(self, query, max_results=6):
        return [
            TavilySearchResult(
                title="Supplement",
                url="https://example.com/supplement",
                content="Extra context",
                score=0.8,
            )
        ]

    async def extract(self, url):
        return "# Extracted"

    async def map(self, **kwargs):
        return TavilyMapResult(base_url=kwargs["url"], results=[f"{kwargs['url']}/docs"])


class UnavailableTavilyClient:
    error = TavilyClientError(
        "所有 Tavily Key 均不可用；请补充有效 Key 或重新生成 Tavily Key",
        code="tavily_all_keys_unavailable",
        key_statuses=[
            {"fingerprint": "tvly…0001", "state": "invalid"},
            {"fingerprint": "tvly…0002", "state": "cooldown", "retry_after_seconds": 30},
        ],
        service={"state": "closed", "retry_after_seconds": 0},
    )

    async def search(self, query, max_results=6):
        raise self.error

    async def extract(self, url):
        raise self.error

    async def map(self, **kwargs):
        raise self.error


async def test_web_search_merges_grok_and_tavily_sources(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: FakeGrokClient())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: FakeTavilyClient())

    result = await web_tools.web_search("question", extra_sources=2)
    sources = await web_tools.get_sources(result.session_id)

    assert result.content == "Answer"
    assert result.sources_count == 2
    assert [source.provider for source in sources.sources] == [None, "tavily"]


async def test_web_fetch_and_map_return_structured_models(monkeypatch):
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: FakeTavilyClient())

    fetched = await web_tools.web_fetch("https://example.com")
    mapped = await web_tools.web_map("https://example.com")

    assert fetched.provider == "tavily"
    assert fetched.content == "# Extracted"
    assert mapped.base_url == "https://example.com"
    assert mapped.results == ["https://example.com/docs"]


async def test_web_fetch_reports_missing_tavily_configuration():
    result = await web_tools.web_fetch("https://example.com")

    assert result.content == ""
    assert "TAVILY_API_KEY" in result.error


async def test_web_search_marks_tavily_supplement_failure_as_partial(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("TAVILY_API_KEYS", "tvly-secret-0001,tvly-secret-0002")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: FakeGrokClient())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: UnavailableTavilyClient())

    result = await web_tools.web_search("question", extra_sources=2)

    assert result.content == "Answer"
    assert result.partial is True
    assert result.tavily_error is not None
    assert result.tavily_error.code == "tavily_all_keys_unavailable"
    assert result.tavily_error.key_statuses[0]["fingerprint"] == "tvly…0001"


async def test_fetch_and_map_return_structured_all_keys_unavailable(monkeypatch):
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: UnavailableTavilyClient())

    fetched = await web_tools.web_fetch("https://example.com")
    mapped = await web_tools.web_map("https://example.com")

    assert fetched.content == ""
    assert fetched.provider is None
    assert fetched.tavily_error is not None
    assert fetched.tavily_error.code == "tavily_all_keys_unavailable"
    assert mapped.results == []
    assert mapped.tavily_error is not None
    assert mapped.tavily_error.code == "tavily_all_keys_unavailable"


async def test_web_search_does_not_return_empty_success_when_both_providers_fail(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("TAVILY_API_KEYS", "tvly-secret-0001,tvly-secret-0002")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: FailingGrokClient())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: UnavailableTavilyClient())

    result = await web_tools.web_search("question", extra_sources=2)

    assert result.content == ""
    assert result.partial is False
    assert result.error == "tavily_all_keys_unavailable"
    assert result.tavily_error is not None
