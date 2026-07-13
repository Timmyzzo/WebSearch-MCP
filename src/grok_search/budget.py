from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable


class RequestBudget:
    """Monotonic wall-clock budget shared by one tool call and its upstream work."""

    def __init__(
        self,
        total_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if total_seconds <= 0:
            raise ValueError("总时间预算必须大于 0")
        self.total_seconds = float(total_seconds)
        self._clock = clock
        self.started_at = clock()
        self.deadline = self.started_at + self.total_seconds
        self._queue_wait: dict[str, float] = defaultdict(float)

    def remaining(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    def record_queue_wait(self, service: str, seconds: float) -> None:
        self._queue_wait[service] += max(0.0, seconds)

    def queue_wait_seconds(self, service: str | None = None) -> float:
        if service is None:
            return sum(self._queue_wait.values())
        return self._queue_wait.get(service, 0.0)

    @property
    def elapsed_ms(self) -> int:
        return round(self.elapsed_seconds() * 1000)

    @property
    def budget_ms(self) -> int:
        return round(self.total_seconds * 1000)

    def queue_wait_ms(self, service: str | None = None) -> int:
        return round(self.queue_wait_seconds(service) * 1000)
