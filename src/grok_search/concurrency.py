from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .budget import RequestBudget


class ConcurrencySlotTimeout(TimeoutError):
    def __init__(self, service: str) -> None:
        super().__init__(f"等待 {service} 并发槽位时预算耗尽")
        self.service = service


class AsyncConcurrencyLimiter:
    """Cancellation-safe async limiter used by all requests in one MCP process."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("并发上限必须大于或等于 1")
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @asynccontextmanager
    async def slot(
        self,
        budget: RequestBudget,
        *,
        service: str,
    ) -> AsyncIterator[None]:
        wait_started = time.monotonic()
        remaining = budget.remaining()
        if remaining <= 0:
            raise ConcurrencySlotTimeout(service)
        try:
            async with asyncio.timeout(remaining):
                await self._semaphore.acquire()
        except TimeoutError as exc:
            budget.record_queue_wait(service, time.monotonic() - wait_started)
            raise ConcurrencySlotTimeout(service) from exc

        budget.record_queue_wait(service, time.monotonic() - wait_started)
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1
            self._semaphore.release()
