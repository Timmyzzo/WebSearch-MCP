from grok_search.models import TavilyMapResult, TavilySearchResult
from grok_search.tools import web as web_tools


class FakeGrokClient:
    async def search(self, query, platform=""):
        return "Answer\n\nSources:\n- [Official](https://example.com/official)"


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
