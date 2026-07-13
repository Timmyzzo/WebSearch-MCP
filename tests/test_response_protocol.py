import asyncio
import json

import httpx

from grok_search.clients.grok import GrokClientError, _AttemptFailure
from grok_search.clients.tavily import TavilyClient, TavilyClientError
from grok_search.models import ErrorDetail, TavilyMapResult, TavilySearchResult
from grok_search.tools import configuration as configuration_tools
from grok_search.tools import planning as planning_tools
from grok_search.tools import web as web_tools


def grok_failure(error_type: str = "upstream_unavailable") -> GrokClientError:
    action = "fatal" if error_type in {"authentication_error", "request_invalid"} else "retry"
    code = {
        "authentication_error": "grok_authentication_error",
        "request_invalid": "grok_request_invalid",
    }.get(error_type, "grok_primary_failed")
    return GrokClientError(
        code=code,
        message="Grok request failed",
        primary_model="primary",
        fallback_model=None,
        primary_attempts=1,
        fallback_attempts=0,
        last_failure=_AttemptFailure(
            error_type,
            action=action,
            http_status=401 if error_type == "authentication_error" else 503,
            upstream_code=error_type,
        ),
        switched_model=False,
    )


class GrokAnswer:
    def __init__(self, answer: str = "Answer"):
        self.answer = answer

    async def search(self, query, platform="", **kwargs):
        return self.answer

    async def aclose(self):
        return None


class GrokFails:
    def __init__(self, error_type: str = "upstream_unavailable"):
        self.error_type = error_type

    async def search(self, query, platform="", **kwargs):
        raise grok_failure(self.error_type)

    async def aclose(self):
        return None


class TavilyResults:
    async def search(self, query, max_results=6):
        return [
            TavilySearchResult(
                title="Docs",
                url="https://example.com/docs",
                content="Context",
                score=0.9,
            )
        ]

    async def extract(self, url):
        return "# Content"

    async def map(self, **kwargs):
        return TavilyMapResult(
            base_url=kwargs["url"],
            results=[f"{kwargs['url']}/docs"],
            response_time=0.1,
        )


class TavilyFails:
    def __init__(self, code: str = "tavily_service_unavailable"):
        self.error = TavilyClientError(
            "Tavily unavailable",
            code=code,
            retryable=code == "tavily_service_unavailable",
            http_status=503 if code == "tavily_service_unavailable" else 400,
            upstream_code="upstream_unavailable",
            key_statuses=[{"fingerprint": "tvly…0001", "state": "cooldown"}],
            service={"state": "open", "retry_after_seconds": 30},
        )

    async def search(self, query, max_results=6):
        raise self.error

    async def extract(self, url):
        raise self.error

    async def map(self, **kwargs):
        raise self.error


def configure_grok(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "grok-secret")
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "primary")


def configure_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEYS", "tvly-secret-0001,tvly-secret-0002")


def assert_error_schema(detail: ErrorDetail, *, service: str, code: str):
    assert detail.code == code
    assert detail.service == service
    assert isinstance(detail.message, str) and detail.message
    assert isinstance(detail.retryable, bool)
    assert isinstance(detail.diagnostics, dict)


async def test_web_search_all_provider_combinations_and_legacy_mapping(monkeypatch):
    configure_grok(monkeypatch)
    configure_tavily(monkeypatch)

    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokAnswer())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyResults())
    success = await web_tools.web_search("success", extra_sources=1)
    assert success.status == "success"
    assert success.partial is False
    assert success.error is None
    assert success.error_detail is None
    assert success.content == "Answer"
    assert success.sources_count == 1

    await web_tools.close_grok_client()
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokAnswer())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyFails())
    partial = await web_tools.web_search("partial", extra_sources=1)
    assert partial.status == "partial_success"
    assert partial.partial is True
    assert partial.error is None
    assert partial.tavily_error is not None
    assert partial.error_detail is not None
    assert_error_schema(
        partial.error_detail, service="tavily", code="tavily_service_unavailable"
    )

    await web_tools.close_grok_client()
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokFails())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyResults())
    grok_only_error = await web_tools.web_search("grok fails", extra_sources=1)
    assert grok_only_error.status == "error"
    assert grok_only_error.content == ""
    assert grok_only_error.sources_count == 0
    assert grok_only_error.error == "grok_primary_failed"
    assert grok_only_error.grok_error is not None
    assert grok_only_error.tavily_error is None

    await web_tools.close_grok_client()
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokFails())
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyFails())
    both_error = await web_tools.web_search("both fail", extra_sources=1)
    assert both_error.status == "error"
    assert both_error.grok_error is not None
    assert both_error.tavily_error is not None
    assert both_error.error_detail is not None
    assert both_error.error_detail.diagnostics["component_errors"]["tavily"]["code"] == (
        "tavily_service_unavailable"
    )


async def test_web_search_answer_without_sources_is_success_and_empty_answer_is_error(monkeypatch):
    configure_grok(monkeypatch)
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokAnswer("Valid answer"))

    result = await web_tools.web_search("no sources")
    assert result.status == "success"
    assert result.content == "Valid answer"
    assert result.sources_count == 0
    cached = await web_tools.get_sources(result.session_id)
    assert cached.status == "success"
    assert cached.sources == []

    await web_tools.close_grok_client()
    monkeypatch.setattr(
        web_tools,
        "_new_grok_client",
        lambda *args: GrokAnswer("Sources:\n- [Only](https://example.com)"),
    )
    empty = await web_tools.web_search("sources only")
    assert empty.status == "error"
    assert empty.error == "grok_empty_answer"
    assert empty.error_detail is not None
    assert empty.error_detail.diagnostics["upstream_succeeded"] is True
    uncached = await web_tools.get_sources(empty.session_id)
    assert uncached.status == "error"


async def test_grok_auth_request_and_stream_errors_keep_stable_details(monkeypatch):
    configure_grok(monkeypatch)
    for error_type, expected_code, retryable in (
        ("authentication_error", "grok_authentication_error", False),
        ("request_invalid", "grok_request_invalid", False),
        ("stream_interrupted_after_content", "grok_primary_failed", True),
    ):
        await web_tools.close_grok_client()
        monkeypatch.setattr(
            web_tools, "_new_grok_client", lambda *args, kind=error_type: GrokFails(kind)
        )
        result = await web_tools.web_search(error_type)
        assert result.status == "error"
        assert result.error == expected_code
        assert result.error_detail is not None
        assert result.error_detail.retryable is retryable
        assert result.grok_error is not None
        assert result.grok_error.last_error_type == error_type


async def test_unconfigured_grok_and_tavily_are_structured_errors(monkeypatch):
    grok = await web_tools.web_search("missing grok")
    assert grok.status == "error"
    assert grok.error == "grok_configuration_error"
    assert_error_schema(grok.error_detail, service="grok", code="grok_configuration_error")

    fetch = await web_tools.web_fetch("https://example.com")
    assert fetch.status == "error"
    assert fetch.tavily_error is not None
    assert fetch.tavily_error.code == "tavily_configuration_error"
    assert_error_schema(fetch.error_detail, service="tavily", code="tavily_configuration_error")

    configure_grok(monkeypatch)
    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: GrokAnswer())
    search = await web_tools.web_search("missing tavily", extra_sources=1)
    assert search.status == "partial_success"
    assert search.tavily_error is not None
    assert search.tavily_error.code == "tavily_configuration_error"


async def test_fetch_and_map_distinguish_success_empty_partial_and_upstream_error(monkeypatch):
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyResults())
    fetched = await web_tools.web_fetch("https://example.com")
    mapped = await web_tools.web_map("https://example.com")
    assert fetched.status == "success"
    assert fetched.content == "# Content"
    assert mapped.status == "success"
    assert mapped.results

    class EmptyTavily(TavilyResults):
        async def extract(self, url):
            return None

        async def map(self, **kwargs):
            return TavilyMapResult(base_url=kwargs["url"], results=[])

    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: EmptyTavily())
    empty_fetch = await web_tools.web_fetch("https://example.com")
    empty_map = await web_tools.web_map("https://example.com")
    assert empty_fetch.status == "error"
    assert empty_fetch.error_detail.code == "tavily_no_content"
    assert empty_fetch.error_detail.diagnostics["empty_result"] is True
    assert empty_map.status == "error"
    assert empty_map.error_detail.code == "tavily_no_urls"

    class PartialMap(TavilyResults):
        async def map(self, **kwargs):
            return TavilyMapResult(
                base_url="",
                results=[f"{kwargs['url']}/docs"],
                ignored_results=1,
            )

    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: PartialMap())
    partial_map = await web_tools.web_map("https://example.com")
    assert partial_map.status == "partial_success"
    assert partial_map.partial is True
    assert partial_map.results == ["https://example.com/docs"]
    assert partial_map.error_detail.code == "tavily_map_incomplete"

    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: TavilyFails())
    failed_fetch = await web_tools.web_fetch("https://example.com")
    failed_map = await web_tools.web_map("https://example.com")
    assert failed_fetch.status == failed_map.status == "error"
    assert failed_fetch.error_detail.http_status == 503
    assert failed_map.tavily_error.service["state"] == "open"

    monkeypatch.setattr(
        web_tools,
        "_new_tavily_client",
        lambda: TavilyFails("tavily_request_invalid"),
    )
    invalid = await web_tools.web_fetch("https://example.com")
    assert invalid.status == "error"
    assert invalid.error_detail.code == "tavily_request_invalid"
    assert invalid.error_detail.retryable is False
    assert invalid.error_detail.http_status == 400

    all_keys = TavilyFails("tavily_all_keys_unavailable")
    all_keys.error.key_statuses = [
        {"fingerprint": "tvly…0001", "state": "invalid"},
        {"fingerprint": "tvly…0002", "state": "quota_exhausted"},
    ]
    monkeypatch.setattr(web_tools, "_new_tavily_client", lambda: all_keys)
    unavailable = await web_tools.web_map("https://example.com")
    assert unavailable.status == "error"
    assert unavailable.tavily_error.code == "tavily_all_keys_unavailable"
    assert unavailable.error_detail.diagnostics["key_statuses"][0]["state"] == "invalid"


async def test_sources_success_partial_and_error_are_distinct():
    empty_id = "empty-session"
    await web_tools._SOURCES_CACHE.set(empty_id, [])
    empty = await web_tools.get_sources(empty_id)
    assert empty.status == "success"
    assert empty.sources == []

    mixed_id = "mixed-session"
    await web_tools._SOURCES_CACHE.set(
        mixed_id,
        [{"url": "https://example.com"}, {"title": "missing url"}],
    )
    partial = await web_tools.get_sources(mixed_id)
    assert partial.status == "partial_success"
    assert partial.sources_count == 1
    assert partial.error_detail.code == "sources_partially_invalid"

    missing = await web_tools.get_sources("does-not-exist")
    assert missing.status == "error"
    assert missing.error == "session_id_not_found_or_expired"


async def test_config_info_success_partial_and_error(monkeypatch):
    configure_grok(monkeypatch)

    class ModelClient:
        async def list_models(self):
            return ["primary", "fallback"]

    async def get_client(*args):
        return ModelClient()

    monkeypatch.setattr(web_tools, "_get_grok_client", get_client)
    success = await configuration_tools.get_config_info()
    assert success.status == "success"
    assert success.connection_test.available_models == ["primary", "fallback"]

    monkeypatch.setenv("GROK_MODEL_MAX_ATTEMPTS", "0")
    invalid_attempts = await configuration_tools.get_config_info()
    assert invalid_attempts.status == "partial_success"
    assert invalid_attempts.error_detail.code == "grok_configuration_error"
    monkeypatch.delenv("GROK_MODEL_MAX_ATTEMPTS")

    monkeypatch.delenv("GROK_API_KEY")
    partial = await configuration_tools.get_config_info()
    assert partial.status == "partial_success"
    assert partial.error_detail.code == "grok_configuration_error"

    monkeypatch.setattr(
        configuration_tools.config,
        "get_config_info",
        lambda: (_ for _ in ()).throw(RuntimeError("secret traceback-like body")),
    )
    error = await configuration_tools.get_config_info()
    assert error.status == "error"
    assert error.configuration == {}
    assert error.error_detail.diagnostics == {"exception_type": "RuntimeError"}
    assert "secret traceback-like body" not in error.model_dump_json()


async def test_switch_model_success_and_sanitized_error(monkeypatch, tmp_path):
    from grok_search.config import config

    config._config_file = tmp_path / "config.json"
    success = await configuration_tools.switch_model("new-primary")
    assert success.status == "success"
    assert success.success is True
    assert success.error is None

    raw_key = "grok-super-secret-key"
    monkeypatch.setenv("GROK_API_KEY", raw_key)
    monkeypatch.setattr(
        config,
        "set_model",
        lambda model: (_ for _ in ()).throw(
            RuntimeError(f"Authorization: Bearer {raw_key}; response credential=leaked")
        ),
    )
    failed = await configuration_tools.switch_model("other")
    serialized = failed.model_dump_json()
    assert failed.status == "error"
    assert failed.success is False
    assert failed.error_detail.code == "model_switch_failed"
    assert raw_key not in serialized
    assert "leaked" not in serialized
    assert "Authorization" not in serialized


async def test_planning_tools_use_all_three_statuses_and_reject_invalid_json():
    intent = await planning_tools.plan_intent("question", "factual", "recent")
    assert intent.status == "partial_success"
    assert intent.partial is True
    assert intent.error is None
    assert intent.error_detail.code == "planning_incomplete"

    complexity = await planning_tools.plan_complexity(
        intent.session_id,
        level=1,
        estimated_sub_queries=1,
        estimated_tool_calls=1,
        justification="simple",
    )
    assert complexity.status == "partial_success"

    complete = await planning_tools.plan_sub_query(
        intent.session_id,
        id="q1",
        goal="find answer",
        expected_output="fact",
        boundary="official sources",
    )
    assert complete.status == "success"
    assert complete.plan_complete is True
    assert complete.executable_plan is not None

    missing = await planning_tools.plan_complexity(
        "missing",
        level=1,
        estimated_sub_queries=1,
        estimated_tool_calls=1,
        justification="simple",
    )
    assert missing.status == "error"
    assert missing.error_detail.code == "planning_session_not_found"

    invalid_json = await planning_tools.plan_tool_mapping(
        intent.session_id,
        sub_query_id="q1",
        tool="web_search",
        reason="search",
        params_json="{not json}",
    )
    assert invalid_json.status == "error"
    assert invalid_json.error_detail.code == "planning_invalid_params_json"


async def test_tavily_response_body_credentials_are_never_returned():
    raw_key = "tvly-super-secret-key"
    other_credential = "upstream-private-credential"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "invalid_parameter",
                    "message": (
                        f"Authorization: Bearer {raw_key}; credential={other_credential}"
                    ),
                }
            },
        )

    client = TavilyClient(
        "https://api.tavily.com",
        [raw_key],
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.search("query")
    except TavilyClientError as exc:
        serialized = json.dumps(exc.to_dict(), ensure_ascii=False)
    else:
        raise AssertionError("TavilyClientError was not raised")
    finally:
        await client.aclose()

    assert raw_key not in serialized
    assert other_credential not in serialized
    assert "Authorization" not in serialized
    assert "invalid_parameter" in serialized


async def test_concurrent_tool_calls_do_not_share_response_or_error_state(monkeypatch):
    configure_grok(monkeypatch)

    class ConcurrentGrok:
        async def search(self, query, platform="", **kwargs):
            if query == "ok":
                return "Concurrent answer"
            raise grok_failure()

        async def aclose(self):
            return None

    monkeypatch.setattr(web_tools, "_new_grok_client", lambda *args: ConcurrentGrok())
    success, first_error, second_error = await asyncio.gather(
        web_tools.web_search("ok"),
        web_tools.web_search("first failure"),
        web_tools.web_search("second failure"),
    )

    assert success.status == "success"
    assert first_error.status == second_error.status == "error"
    assert len({success.session_id, first_error.session_id, second_error.session_id}) == 3
    assert first_error.error_detail is not second_error.error_detail
    first_error.error_detail.diagnostics["mutated"] = True
    assert "mutated" not in second_error.error_detail.diagnostics
