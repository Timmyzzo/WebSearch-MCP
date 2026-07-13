import pytest

from grok_search.config import config


def test_grok_primary_model_configuration_priority(monkeypatch, tmp_path):
    config._config_file = tmp_path / "config.json"
    config.set_model("file-primary")
    config._cached_model = None
    monkeypatch.setenv("GROK_MODEL", "legacy-primary")
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "explicit-primary")

    assert config.grok_primary_model == "explicit-primary"
    assert config.grok_model == "explicit-primary"


def test_grok_model_legacy_and_empty_values(monkeypatch, tmp_path):
    config._config_file = tmp_path / "config.json"
    config.set_model("file-primary")
    config._cached_model = None
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "   ")
    monkeypatch.setenv("GROK_MODEL", "legacy-primary")
    monkeypatch.setenv("GROK_FALLBACK_MODEL", "  ")

    assert config.grok_primary_model == "legacy-primary"
    assert config.grok_fallback_model is None


def test_grok_model_attempts_default_and_validation(monkeypatch):
    assert config.grok_model_max_attempts == 5
    monkeypatch.setenv("GROK_MODEL_MAX_ATTEMPTS", "7")
    assert config.grok_model_max_attempts == 7
    monkeypatch.setenv("GROK_MODEL_MAX_ATTEMPTS", "0")
    with pytest.raises(ValueError, match="大于或等于 1"):
        _ = config.grok_model_max_attempts


def test_timeout_and_concurrency_defaults_and_safety_bounds(monkeypatch):
    assert config.web_search_total_timeout == 270
    assert config.grok_max_concurrency == 2
    assert config.tavily_per_key_max_concurrency == 1

    monkeypatch.setenv("WEB_SEARCH_TOTAL_TIMEOUT", "240.5")
    monkeypatch.setenv("GROK_MAX_CONCURRENCY", "1")
    assert config.web_search_total_timeout == 240.5
    assert config.grok_max_concurrency == 1

    monkeypatch.setenv("WEB_SEARCH_TOTAL_TIMEOUT", "0")
    with pytest.raises(ValueError, match="大于 0"):
        _ = config.web_search_total_timeout
    monkeypatch.setenv("GROK_MAX_CONCURRENCY", "3")
    with pytest.raises(ValueError, match="1 或 2"):
        _ = config.grok_max_concurrency
    monkeypatch.setenv("TAVILY_PER_KEY_MAX_CONCURRENCY", "2")
    with pytest.raises(ValueError, match="必须为 1"):
        _ = config.tavily_per_key_max_concurrency


def test_openrouter_online_suffix_is_used_for_chat_completions(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("GROK_PRIMARY_MODEL", "x-ai/grok-test")

    config._cached_model = None
    assert config.grok_primary_model == "x-ai/grok-test:online"

def test_tavily_keys_support_all_documented_separators(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEYS", "first, second;third\nfourth\r\nfifth")

    assert config.tavily_api_keys == ["first", "second", "third", "fourth", "fifth"]


def test_tavily_keys_rotate_in_order(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEYS", "one,two,three")

    assert [config.next_tavily_api_key() for _ in range(5)] == [
        "one",
        "two",
        "three",
        "one",
        "two",
    ]


def test_tavily_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEYS", "one,two")
    monkeypatch.setenv("TAVILY_ENABLED", "false")

    assert config.tavily_api_keys == []
    assert config.next_tavily_api_key() is None


def test_config_info_contains_only_current_services(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "https://grok.example/v1")
    monkeypatch.setenv("GROK_API_KEY", "1234567890abcdef")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-1234567890")

    info = config.get_config_info()

    assert info["GROK_API_URL"] == "https://grok.example/v1"
    assert info["GROK_API_KEY"] != "1234567890abcdef"
    assert set(info).issuperset({"GROK_API_URL", "GROK_API_KEY", "TAVILY_API_URL"})
    assert info["GROK_PRIMARY_MODEL"] == "grok-4-fast"
    assert info["GROK_FALLBACK_MODEL"] == "已弃用（单模型模式）"
    assert info["GROK_MODEL_MAX_ATTEMPTS"] == 5
    assert info["GROK_MAX_CONCURRENCY"] == 2
    assert info["WEB_SEARCH_TOTAL_TIMEOUT"] == 270
    assert info["TAVILY_PER_KEY_MAX_CONCURRENCY"] == 1
    assert all("fire" not in key.lower() for key in info)


def test_tavily_reliability_configuration_is_reported_without_raw_keys(monkeypatch):
    raw_key = "tvly-test-1234"
    monkeypatch.setenv("TAVILY_API_KEYS", raw_key)
    monkeypatch.setenv("TAVILY_KEY_COOLDOWN", "12.5")
    monkeypatch.setenv("TAVILY_QUOTA_COOLDOWN", "7200")
    monkeypatch.setenv("TAVILY_SERVICE_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("TAVILY_SERVICE_COOLDOWN", "45")

    info = config.get_config_info()

    assert info["TAVILY_KEY_COOLDOWN"] == 12.5
    assert info["TAVILY_QUOTA_COOLDOWN"] == 7200
    assert info["TAVILY_SERVICE_FAILURE_THRESHOLD"] == 3
    assert info["TAVILY_SERVICE_COOLDOWN"] == 45
    assert raw_key not in str(info)
