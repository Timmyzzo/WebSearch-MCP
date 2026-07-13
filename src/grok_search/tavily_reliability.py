from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum


class TavilyKeyState(str, Enum):
    HEALTHY = "healthy"
    COOLDOWN = "cooldown"
    QUOTA_EXHAUSTED = "quota_exhausted"
    INVALID = "invalid"


class TavilyServiceState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class TavilyConcurrencyTimeout(TimeoutError):
    pass


def key_fingerprint(key: str) -> str:
    """Return a stable, non-secret identifier suitable for diagnostics."""
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())


def redact_keys(text: str, keys: Iterable[str]) -> str:
    redacted = text
    for key in sorted((item for item in keys if item), key=len, reverse=True):
        redacted = redacted.replace(key, key_fingerprint(key))
    return redacted


@dataclass
class TavilyKeyHealth:
    key: str
    state: TavilyKeyState = TavilyKeyState.HEALTHY
    unavailable_until: float = 0.0
    last_error: str | None = None

    def refresh(self, now: float) -> None:
        if self.state in {TavilyKeyState.COOLDOWN, TavilyKeyState.QUOTA_EXHAUSTED}:
            if now >= self.unavailable_until:
                self.state = TavilyKeyState.HEALTHY
                self.unavailable_until = 0.0
                self.last_error = None


class TavilyReliabilityManager:
    """Process-local Tavily key scheduler and service circuit breaker."""

    def __init__(
        self,
        keys: Iterable[str],
        *,
        key_cooldown: float = 30.0,
        quota_cooldown: float = 3600.0,
        service_failure_threshold: int = 2,
        service_cooldown: float = 30.0,
        per_key_max_concurrency: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        unique_keys = list(dict.fromkeys(key for key in keys if key))
        self._keys = [TavilyKeyHealth(key=key) for key in unique_keys]
        self._key_cooldown = max(0.0, key_cooldown)
        self._quota_cooldown = max(0.0, quota_cooldown)
        self._service_failure_threshold = max(2, service_failure_threshold)
        self._service_cooldown = max(0.0, service_cooldown)
        if per_key_max_concurrency < 1:
            raise ValueError("Tavily 每 Key 并发上限必须大于或等于 1")
        self._per_key_max_concurrency = per_key_max_concurrency
        self._clock = clock
        self._cursor = 0
        self._condition = asyncio.Condition()
        self._lock = self._condition
        self._in_flight: dict[str, int] = defaultdict(int)
        self._service_state = TavilyServiceState.CLOSED
        self._service_open_until = 0.0
        self._half_open_key: str | None = None
        self._failures: dict[str, set[str]] = defaultdict(set)

    @property
    def raw_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self._keys)

    @property
    def service_state(self) -> TavilyServiceState:
        return self._service_state

    async def acquire_key(self, excluded: set[str] | None = None) -> str | None:
        """Compatibility scheduler that does not reserve a concurrency slot."""
        excluded = excluded or set()
        async with self._lock:
            key, _ = self._select_key_locked(excluded, reserve=False)
            return key

    async def acquire_key_slot(
        self,
        excluded: set[str] | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        """Reserve one healthy key, waiting only when eligible keys are busy."""
        excluded = excluded or set()
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + max(0.0, timeout)
        async with self._condition:
            while True:
                key, busy = self._select_key_locked(excluded, reserve=True)
                if key is not None:
                    return key
                if not busy:
                    return None
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    raise TavilyConcurrencyTimeout
                try:
                    if remaining is None:
                        await self._condition.wait()
                    else:
                        async with asyncio.timeout(remaining):
                            await self._condition.wait()
                except TimeoutError as exc:
                    raise TavilyConcurrencyTimeout from exc

    async def release_key(self, key: str) -> None:
        async with self._condition:
            if self._in_flight.get(key, 0) > 0:
                self._in_flight[key] -= 1
                if self._in_flight[key] <= 0:
                    self._in_flight.pop(key, None)
            if (
                self._service_state is TavilyServiceState.HALF_OPEN
                and key == self._half_open_key
            ):
                self._open_service(self._clock())
            self._condition.notify_all()

    async def mark_success(self, key: str) -> None:
        async with self._lock:
            item = self._find(key)
            if item:
                item.state = TavilyKeyState.HEALTHY
                item.unavailable_until = 0.0
                item.last_error = None
            if self._service_state is TavilyServiceState.OPEN:
                return
            if self._service_state is TavilyServiceState.HALF_OPEN:
                if key != self._half_open_key:
                    return
            self._failures.clear()
            self._service_state = TavilyServiceState.CLOSED
            self._service_open_until = 0.0
            self._half_open_key = None
            self._condition.notify_all()

    async def mark_invalid(self, key: str, reason: str) -> None:
        async with self._lock:
            item = self._find(key)
            if item:
                item.state = TavilyKeyState.INVALID
                item.unavailable_until = 0.0
                item.last_error = reason
            self._condition.notify_all()

    async def mark_rate_limited(
        self,
        key: str,
        *,
        quota_exhausted: bool,
        retry_after: float | None,
        reason: str,
    ) -> None:
        async with self._lock:
            item = self._find(key)
            if not item:
                return
            item.state = (
                TavilyKeyState.QUOTA_EXHAUSTED
                if quota_exhausted
                else TavilyKeyState.COOLDOWN
            )
            fallback = self._quota_cooldown if quota_exhausted else self._key_cooldown
            cooldown = retry_after if retry_after is not None else fallback
            item.unavailable_until = self._clock() + cooldown
            item.last_error = reason
            self._condition.notify_all()

    async def mark_temporary_failure(self, key: str, signature: str, reason: str) -> None:
        async with self._lock:
            now = self._clock()
            item = self._find(key)
            if item:
                item.state = TavilyKeyState.COOLDOWN
                item.unavailable_until = now + self._key_cooldown
                item.last_error = reason

            if self._service_state is TavilyServiceState.HALF_OPEN:
                self._open_service(now)
                return

            self._failures[signature].add(key)
            if len(self._failures[signature]) >= self._service_failure_threshold:
                self._open_service(now)
            self._condition.notify_all()

    async def status_summary(self) -> list[dict[str, object]]:
        async with self._lock:
            now = self._clock()
            result: list[dict[str, object]] = []
            for item in self._keys:
                item.refresh(now)
                summary: dict[str, object] = {
                    "fingerprint": key_fingerprint(item.key),
                    "state": item.state.value,
                    "in_flight": self._in_flight.get(item.key, 0),
                }
                if item.unavailable_until > now:
                    summary["retry_after_seconds"] = round(item.unavailable_until - now, 3)
                if item.last_error:
                    summary["last_error"] = item.last_error
                result.append(summary)
            return result

    async def service_summary(self) -> dict[str, object]:
        async with self._lock:
            now = self._clock()
            retry_after = max(0.0, self._service_open_until - now)
            return {
                "state": self._service_state.value,
                "retry_after_seconds": round(retry_after, 3),
            }

    def _find(self, key: str) -> TavilyKeyHealth | None:
        return next((item for item in self._keys if item.key == key), None)

    def _select_key_locked(
        self,
        excluded: set[str],
        *,
        reserve: bool,
    ) -> tuple[str | None, bool]:
        now = self._clock()
        service_probe_ready = False
        if self._service_state is TavilyServiceState.OPEN:
            if now < self._service_open_until:
                return None, False
            service_probe_ready = True

        if self._service_state is TavilyServiceState.HALF_OPEN and self._half_open_key:
            return None, False

        busy_eligible = False
        count = len(self._keys)
        for offset in range(count):
            index = (self._cursor + offset) % count
            item = self._keys[index]
            item.refresh(now)
            if item.key in excluded or item.state is not TavilyKeyState.HEALTHY:
                continue
            if reserve and self._in_flight[item.key] >= self._per_key_max_concurrency:
                busy_eligible = True
                continue
            self._cursor = (index + 1) % count
            if service_probe_ready:
                self._service_state = TavilyServiceState.HALF_OPEN
                self._half_open_key = item.key
            if reserve:
                self._in_flight[item.key] += 1
            return item.key, busy_eligible
        return None, busy_eligible

    def _open_service(self, now: float) -> None:
        self._service_state = TavilyServiceState.OPEN
        self._service_open_until = now + self._service_cooldown
        self._half_open_key = None


_INVALID_PATTERN = re.compile(
    r"(?:invalid|revoked|unauthori[sz]ed|authentication|api[_ -]?key).{0,40}"
    r"(?:invalid|revoked|missing|expired)|(?:invalid|revoked).{0,40}(?:api[_ -]?key|token)",
    re.IGNORECASE,
)
_QUOTA_PATTERN = re.compile(
    r"quota|credit|billing|plan limit|usage limit|monthly limit|exhausted|insufficient",
    re.IGNORECASE,
)


def response_error_text(data: object, body: str) -> tuple[str | None, str]:
    code: str | None = None
    message = body
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            raw_code = error.get("code") or error.get("type")
            code = str(raw_code) if raw_code is not None else None
            raw_message = error.get("message") or error.get("detail")
            if raw_message is not None:
                message = str(raw_message)
        else:
            raw_code = data.get("code") or data.get("error_code")
            code = str(raw_code) if raw_code is not None else None
            raw_message = data.get("message") or data.get("detail") or error
            if raw_message is not None:
                message = str(raw_message)
    return code, message


def is_explicitly_invalid(code: str | None, message: str) -> bool:
    combined = f"{code or ''} {message}"
    return bool(_INVALID_PATTERN.search(combined))


def is_quota_exhausted(code: str | None, message: str) -> bool:
    combined = f"{code or ''} {message}"
    return bool(_QUOTA_PATTERN.search(combined))


def network_failure_signature(exc: Exception) -> str:
    name = type(exc).__name__
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"network:{name}:{digest}"
