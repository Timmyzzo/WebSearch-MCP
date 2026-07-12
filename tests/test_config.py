from grok_search.config import config


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
