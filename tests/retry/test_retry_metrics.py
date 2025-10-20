from __future__ import annotations

import asyncio

import pytest

from sma.core.clock import Clock
from sma.core.retry import (
    RetryExhaustedError,
    RetryPolicy,
    execute_with_retry_async,
    execute_with_retry,
    retry_attempts_total,
    retry_backoff_seconds,
    retry_exhaustion_total,
)


class Boom(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _reset_metrics():
    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()
    yield
    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()


def test_retry_metrics_labeled(clock) -> None:  # type: ignore[no-untyped-def]
    clock.tick(seconds=0)
    policy = RetryPolicy(base_delay=0.1, factor=2.0, max_delay=0.2, max_attempts=2)
    tehran = Clock.for_timezone("Asia/Tehran", now_factory=clock.now)

    def action() -> str:
        raise Boom("transient")

    with pytest.raises(RetryExhaustedError):
        execute_with_retry(
            action,
            policy=policy,
            clock=tehran,
            sleeper=lambda seconds: clock.tick(seconds=seconds),
            retryable=(Boom,),
            correlation_id="rid-1",
            op="unit-test",
        )

    counts = retry_attempts_total.collect()[0].samples
    labels = {sample.labels["outcome"] for sample in counts}
    assert {"failure", "retry"}.issubset(labels)


def test_retry_metrics_async(clock) -> None:  # type: ignore[no-untyped-def]
    policy = RetryPolicy(base_delay=0.05, factor=2.0, max_delay=0.1, max_attempts=3)
    tehran = Clock.for_timezone("Asia/Tehran", now_factory=clock.now)
    attempts: list[int] = []

    async def sleeper(seconds: float) -> None:
        clock.tick(seconds=seconds)

    async def action() -> str:
        attempts.append(len(attempts))
        if len(attempts) < 2:
            raise Boom("retry me")
        return "ok"

    result = asyncio.run(
        execute_with_retry_async(
            action,
            policy=policy,
            clock=tehran,
            sleeper=sleeper,
            retryable=(Boom,),
            correlation_id="rid-2",
            op="async-test",
        )
    )

    assert result == "ok"
    histogram_samples = retry_backoff_seconds.collect()[0].samples
    assert histogram_samples, "Backoff histogram should record entries"
