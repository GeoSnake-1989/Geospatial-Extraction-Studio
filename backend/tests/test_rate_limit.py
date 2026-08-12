import asyncio

import pytest

from app.rate_limit import AsyncIntervalLimiter


def test_interval_limiter_spaces_request_starts():
    current_time = 100.0
    delays: list[float] = []

    def clock() -> float:
        return current_time

    async def sleeper(delay: float) -> None:
        nonlocal current_time
        delays.append(delay)
        current_time += delay

    async def run() -> None:
        limiter = AsyncIntervalLimiter(1.0, clock=clock, sleeper=sleeper)
        await limiter.wait()
        await limiter.wait()

    asyncio.run(run())

    assert delays == [pytest.approx(1.0)]


def test_interval_limiter_does_not_delay_after_interval_elapsed():
    current_time = 100.0
    delays: list[float] = []

    def clock() -> float:
        return current_time

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def run() -> None:
        nonlocal current_time
        limiter = AsyncIntervalLimiter(1.0, clock=clock, sleeper=sleeper)
        await limiter.wait()
        current_time += 1.25
        await limiter.wait()

    asyncio.run(run())

    assert delays == []


def test_interval_limiter_rejects_negative_interval():
    with pytest.raises(ValueError, match="non-negative"):
        AsyncIntervalLimiter(-0.1)
