import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from grok_search.tavily_reliability import (
    TavilyKeyState,
    TavilyReliabilityManager,
    TavilyServiceState,
    is_explicitly_invalid,
    is_quota_exhausted,
    key_fingerprint,
    parse_retry_after,
    redact_keys,
)

KEYS = (
    "tvly-alpha-1234567890",
    "tvly-bravo-0987654321",
    "tvly-charlie-1122334455",
)


class FakeClock:
    def __init__(self, value: float = 1_000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def states(manager: TavilyReliabilityManager) -> dict[str, dict[str, object]]:
    return {item["fingerprint"]: item for item in await manager.status_summary()}


async def test_healthy_keys_use_fair_round_robin():
    manager = TavilyReliabilityManager(KEYS)

    selected = [await manager.acquire_key() for _ in range(7)]

    assert selected == [*KEYS, *KEYS, KEYS[0]]


async def test_key_health_is_shared_across_operations_using_the_same_manager():
    manager = TavilyReliabilityManager(KEYS)

    search_key = await manager.acquire_key()
    await manager.mark_invalid(search_key, "HTTP 401")
    extract_key = await manager.acquire_key()
    map_key = await manager.acquire_key()

    assert search_key == KEYS[0]
    assert extract_key == KEYS[1]
    assert map_key == KEYS[2]
    summary = await states(manager)
    assert summary[key_fingerprint(KEYS[0])]["state"] == TavilyKeyState.INVALID.value


@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_failures_permanently_disable_only_that_key(status):
    manager = TavilyReliabilityManager(KEYS[:2])
    failed_key = await manager.acquire_key()

    await manager.mark_invalid(failed_key, f"HTTP {status}")

    assert await manager.acquire_key() == KEYS[1]
    summary = await states(manager)
    failed = summary[key_fingerprint(failed_key)]
    assert failed["state"] == "invalid"
    assert "retry_after_seconds" not in failed


async def test_rate_limit_cooldown_expires_and_key_reenters_rotation():
    clock = FakeClock()
    manager = TavilyReliabilityManager(KEYS[:2], key_cooldown=30, clock=clock)
    limited_key = await manager.acquire_key()

    await manager.mark_rate_limited(
        limited_key,
        quota_exhausted=False,
        retry_after=12,
        reason="temporary rate limit",
    )

    summary = await states(manager)
    assert summary[key_fingerprint(limited_key)]["state"] == "cooldown"
    assert summary[key_fingerprint(limited_key)]["retry_after_seconds"] == 12
    assert await manager.acquire_key() == KEYS[1]

    clock.advance(12)
    assert await manager.acquire_key() == limited_key


async def test_quota_exhaustion_uses_the_longer_quota_cooldown():
    clock = FakeClock()
    manager = TavilyReliabilityManager(KEYS[:2], quota_cooldown=3_600, clock=clock)
    exhausted_key = await manager.acquire_key()

    await manager.mark_rate_limited(
        exhausted_key,
        quota_exhausted=True,
        retry_after=None,
        reason="monthly quota exhausted",
    )

    summary = await states(manager)
    exhausted = summary[key_fingerprint(exhausted_key)]
    assert exhausted["state"] == "quota_exhausted"
    assert exhausted["retry_after_seconds"] == 3_600

    clock.advance(3_599)
    assert await manager.acquire_key(excluded={KEYS[1]}) is None
    clock.advance(1)
    assert await manager.acquire_key(excluded={KEYS[1]}) == exhausted_key


async def test_temporary_failures_cool_down_without_invalidating_the_key():
    clock = FakeClock()
    manager = TavilyReliabilityManager(KEYS, key_cooldown=20, clock=clock)
    failed_key = await manager.acquire_key()

    await manager.mark_temporary_failure(failed_key, "http:503", "HTTP 503")

    summary = await states(manager)
    failed = summary[key_fingerprint(failed_key)]
    assert failed["state"] == "cooldown"
    assert failed["retry_after_seconds"] == 20
    assert await manager.acquire_key() == KEYS[1]


async def test_distinct_keys_with_same_temporary_failure_open_service_circuit():
    clock = FakeClock()
    manager = TavilyReliabilityManager(
        KEYS,
        service_failure_threshold=2,
        service_cooldown=60,
        clock=clock,
    )

    first = await manager.acquire_key()
    await manager.mark_temporary_failure(first, "http:503", "HTTP 503")
    second = await manager.acquire_key()
    await manager.mark_temporary_failure(second, "http:503", "HTTP 503")

    assert manager.service_state is TavilyServiceState.OPEN
    assert await manager.acquire_key() is None
    assert await manager.service_summary() == {
        "state": "open",
        "retry_after_seconds": 60,
    }


async def test_repeated_failure_from_one_key_does_not_open_service_circuit():
    manager = TavilyReliabilityManager(KEYS, service_failure_threshold=2)

    await manager.mark_temporary_failure(KEYS[0], "network:timeout", "timeout")
    await manager.mark_temporary_failure(KEYS[0], "network:timeout", "timeout")

    assert manager.service_state is TavilyServiceState.CLOSED


async def test_half_open_allows_exactly_one_concurrent_probe_and_success_recovers():
    clock = FakeClock()
    manager = TavilyReliabilityManager(
        KEYS,
        key_cooldown=0,
        service_failure_threshold=2,
        service_cooldown=10,
        clock=clock,
    )
    await manager.mark_temporary_failure(KEYS[0], "http:503", "HTTP 503")
    await manager.mark_temporary_failure(KEYS[1], "http:503", "HTTP 503")
    clock.advance(10)

    probes = await asyncio.gather(*(manager.acquire_key() for _ in range(8)))

    assert len([key for key in probes if key is not None]) == 1
    probe_key = next(key for key in probes if key is not None)
    assert manager.service_state is TavilyServiceState.HALF_OPEN

    await manager.mark_success(probe_key)

    assert manager.service_state is TavilyServiceState.CLOSED
    assert await manager.acquire_key() is not None


async def test_failed_half_open_probe_reopens_service_circuit():
    clock = FakeClock()
    manager = TavilyReliabilityManager(
        KEYS,
        key_cooldown=0,
        service_failure_threshold=2,
        service_cooldown=10,
        clock=clock,
    )
    await manager.mark_temporary_failure(KEYS[0], "http:503", "HTTP 503")
    await manager.mark_temporary_failure(KEYS[1], "http:503", "HTTP 503")
    clock.advance(10)
    probe_key = await manager.acquire_key()

    await manager.mark_temporary_failure(probe_key, "http:503", "HTTP 503")

    assert manager.service_state is TavilyServiceState.OPEN
    assert (await manager.service_summary())["retry_after_seconds"] == 10


async def test_stale_in_flight_success_does_not_close_an_open_service_circuit():
    clock = FakeClock()
    manager = TavilyReliabilityManager(KEYS, service_failure_threshold=2, clock=clock)

    await manager.mark_temporary_failure(KEYS[0], "http:503", "HTTP 503")
    await manager.mark_temporary_failure(KEYS[1], "http:503", "HTTP 503")
    await manager.mark_success(KEYS[2])

    assert manager.service_state is TavilyServiceState.OPEN
    assert await manager.acquire_key() is None


async def test_service_enters_half_open_only_after_a_probe_key_is_available():
    clock = FakeClock()
    manager = TavilyReliabilityManager(
        KEYS[:2],
        key_cooldown=30,
        service_failure_threshold=2,
        service_cooldown=10,
        clock=clock,
    )
    await manager.mark_temporary_failure(KEYS[0], "http:503", "HTTP 503")
    await manager.mark_temporary_failure(KEYS[1], "http:503", "HTTP 503")
    clock.advance(10)

    assert await manager.acquire_key() is None
    assert manager.service_state is TavilyServiceState.OPEN

    clock.advance(20)
    assert await manager.acquire_key() is not None
    assert manager.service_state is TavilyServiceState.HALF_OPEN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120", 120),
        ("0", 0),
        ("-5", 0),
        ("not-a-date", None),
        (None, None),
    ],
)
def test_retry_after_parses_numeric_and_invalid_values(value, expected):
    assert parse_retry_after(value) == expected


def test_retry_after_parses_http_date_and_clamps_past_dates():
    now = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
    future = now + timedelta(seconds=75)
    past = now - timedelta(seconds=10)

    assert parse_retry_after(future.strftime("%a, %d %b %Y %H:%M:%S GMT"), now=now) == 75
    assert parse_retry_after(past.strftime("%a, %d %b %Y %H:%M:%S GMT"), now=now) == 0


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("invalid_api_key", "authentication failed"),
        ("token_revoked", "The API token was revoked"),
        (None, "API key is invalid or expired"),
    ],
)
def test_explicit_invalid_key_signals_are_detected(code, message):
    assert is_explicitly_invalid(code, message)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("quota_exceeded", "monthly quota exhausted"),
        ("insufficient_credits", "please update billing"),
        (None, "plan limit reached"),
    ],
)
def test_quota_exhaustion_signals_are_detected(code, message):
    assert is_quota_exhausted(code, message)


def test_fingerprints_and_redaction_never_expose_complete_keys():
    text = f"failed keys: {KEYS[0]}, {KEYS[1]}"

    redacted = redact_keys(text, KEYS)

    assert key_fingerprint(KEYS[0]) == "tvly…7890"
    assert key_fingerprint("short") == "***"
    assert KEYS[0] not in redacted
    assert KEYS[1] not in redacted
    assert key_fingerprint(KEYS[0]) in redacted
    assert key_fingerprint(KEYS[1]) in redacted
