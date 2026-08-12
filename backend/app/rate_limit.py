from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class AsyncIntervalLimiter:
    """Spaces request starts across all callers in this process."""

    def __init__(
        self,
        minimum_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if minimum_interval < 0:
            raise ValueError("minimum_interval must be non-negative")
        self.minimum_interval = minimum_interval
        self._clock = clock
        self._sleeper = sleeper
        self._lock = asyncio.Lock()
        self._last_started: float | None = None

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._last_started is not None:
                delay = self.minimum_interval - (now - self._last_started)
                if delay > 0:
                    await self._sleeper(delay)
            self._last_started = self._clock()
