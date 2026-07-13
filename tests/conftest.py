import pytest

from grok_search.config import config


@pytest.fixture(autouse=True)
def reset_config_state(monkeypatch: pytest.MonkeyPatch, tmp_path):
    config._config_file = tmp_path / "config.json"
    for name in (
        "GROK_API_URL",
        "GROK_API_KEY",
        "GROK_MODEL",
        "GROK_PRIMARY_MODEL",
        "GROK_FALLBACK_MODEL",
        "GROK_MODEL_MAX_ATTEMPTS",
        "GROK_MAX_CONCURRENCY",
        "WEB_SEARCH_TOTAL_TIMEOUT",
        "GROK_RETRY_MULTIPLIER",
        "GROK_RETRY_MAX_WAIT",
        "GROK_SINGLE_ATTEMPT_TIMEOUT",
        "GROK_RETRYABLE_UPSTREAM_CODES",
        "TAVILY_API_KEY",
        "TAVILY_API_KEYS",
        "TAVILY_API_URL",
        "TAVILY_ENABLED",
        "TAVILY_KEY_COOLDOWN",
        "TAVILY_QUOTA_COOLDOWN",
        "TAVILY_SERVICE_FAILURE_THRESHOLD",
        "TAVILY_SERVICE_COOLDOWN",
        "TAVILY_PER_KEY_MAX_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)
    config._cached_model = None
    config._tavily_key_index = 0
    try:
        from grok_search.tools import web

        web._GROK_CLIENT = None
        web._GROK_CLIENT_SIGNATURE = None
        web._GROK_CONCURRENCY_LIMITER = None
        web._TAVILY_CLIENT = None
        web._AVAILABLE_MODELS_CACHE.clear()
        web._SOURCES_CACHE._cache.clear()
    except ImportError:
        pass
    try:
        from grok_search.planning import engine

        engine._sessions.clear()
    except ImportError:
        pass
    yield
    config._config_file = None
    config._cached_model = None
    config._tavily_key_index = 0
