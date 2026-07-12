import pytest

from grok_search.config import config


@pytest.fixture(autouse=True)
def reset_config_state(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "GROK_API_URL",
        "GROK_API_KEY",
        "GROK_MODEL",
        "TAVILY_API_KEY",
        "TAVILY_API_KEYS",
        "TAVILY_API_URL",
        "TAVILY_ENABLED",
        "TAVILY_KEY_COOLDOWN",
        "TAVILY_QUOTA_COOLDOWN",
        "TAVILY_SERVICE_FAILURE_THRESHOLD",
        "TAVILY_SERVICE_COOLDOWN",
    ):
        monkeypatch.delenv(name, raising=False)
    config._cached_model = None
    config._tavily_key_index = 0
    yield
    config._cached_model = None
    config._tavily_key_index = 0
