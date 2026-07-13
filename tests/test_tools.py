from grok_search.clients.tavily import TavilyClientError
from grok_search.models import TavilyMapResult, TavilySearchResult
from grok_search.tools import configuration as configuration_tools
from grok_search.tools import web as web_tools


class FakeGrokClient:
    async def search(self, query, platform="", **kwargs):
        return "Answer\n\nSources:\n- [Official](https://example.com/official)"


class FailingGrokClient:
    async def search(self, query, platform="", **kwargs):
        from grok_search.clients.grok import GrokClientError, _AttemptFailure

        raise GrokClientError(
            code="grok_primary_and_fallback_failed",
            message="Grok 主模型和备用模型均不可用",
            primary_model="primary",
            fallback_model="fallback",
            primary_attempts=2,
            fallback_attempts=2,
            last_failure=_AttemptFailure("upstream_unavailable", action="retry", http_status=503),
            switched_model=True,
        )


class FakeClosableGrokClient:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


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


async def test_web_search_feeds_tavily_candidates_into_grok_synthesis(monkeypatch):
    captured = {}

    class CapturingGrokClient:
        async def search(self, query, platform="", **kwargs):
            captured["supplemental_sources"] = kwargs["supplemental_sources"]
            return "Synthesized answer"

    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "fake-grok-key")
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: CapturingGrokClient())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: FakeTavilyClient())

    result = await web_tools.web_search("ambiguous public profile", extra_sources=3)

    assert result.status == "success"
    assert captured["supplemental_sources"] == [
        {
            "url": "https://example.com/supplement",
            "provider": "tavily",
            "title": "Supplement",
            "snippet": "Extra context",
        }
    ]


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
    assert result.error == "grok_primary_and_fallback_failed"
    assert result.grok_error is not None
    assert result.grok_error.total_attempts == 4
    assert result.tavily_error is not None


async def test_tavily_success_does_not_masquerade_as_grok_answer(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: FailingGrokClient())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: FakeTavilyClient())

    result = await web_tools.web_search("question", extra_sources=2)
    sources = await web_tools.get_sources(result.session_id)

    assert result.content == ""
    assert result.error == "grok_primary_and_fallback_failed"
    assert result.sources_count == 0
    assert sources.sources == []
    assert result.tavily_error is None


async def test_shared_grok_client_pool_is_reused_and_closed(monkeypatch):
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: FakeClosableGrokClient())

    first = await web_tools._get_grok_client("https://grok.example/v1", "secret")
    second = await web_tools._get_grok_client("https://grok.example/v1", "secret")
    await web_tools.close_grok_client()

    assert first is second
    assert first.closed is True


async def test_switch_model_persists_and_changes_primary_model(tmp_path):
    from grok_search.config import config

    config._config_file = tmp_path / "config.json"
    config._cached_model = None

    result = await configuration_tools.switch_model("new-primary")

    assert result.success is True
    assert result.current_model == "new-primary"
    assert "主模型" in result.message
    saved = config._load_config_file()
    assert saved["primary_model"] == "new-primary"
    assert saved["model"] == "new-primary"


async def test_invalid_model_attempt_configuration_is_structured(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "secret")
    monkeypatch.setenv("GROK_MODEL_MAX_ATTEMPTS", "0")

    result = await web_tools.web_search("question")

    assert result.error == "grok_configuration_error"
    assert "GROK_MODEL_MAX_ATTEMPTS" in result.content
