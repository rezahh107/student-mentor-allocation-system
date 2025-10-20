from __future__ import annotations

import asyncio

import pytest

from sma.core.clock import FrozenClock, tehran_clock
from sma.core.retry import (
    RetryExhaustedError,
    RetryPolicy,
    build_async_clock_sleeper,
    build_sync_clock_sleeper,
    execute_with_retry,
    execute_with_retry_async,
)


class _Boom(RuntimeError):
    pass


def test_exhaustion_message_deterministic_sync() -> None:
    clock = tehran_clock()
    policy = RetryPolicy(base_delay=0.1, factor=2, max_attempts=2)

    def flaky() -> int:
        raise _Boom("boom")

    sleeper = build_sync_clock_sleeper(clock)

    with pytest.raises(RetryExhaustedError) as excinfo:
        execute_with_retry(
            flaky,
            policy=policy,
            clock=clock,
            sleeper=sleeper,
            retryable=(_Boom,),
            correlation_id="rid-sync",
            op="sync-op",
        )

    assert "RETRY_EXHAUSTED" in str(excinfo.value)
    assert excinfo.value.correlation_id == "rid-sync"
    assert isinstance(excinfo.value.last_error, _Boom)


def test_exhaustion_message_deterministic_async() -> None:
    frozen = FrozenClock(timezone=tehran_clock().timezone)
    now = tehran_clock().now()
    frozen.set(now)
    policy = RetryPolicy(base_delay=0.1, factor=2, max_attempts=2)

    async def flaky_async() -> int:
        raise _Boom("boom")

    sleeper = build_async_clock_sleeper(frozen)

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(
            execute_with_retry_async(
                flaky_async,
                policy=policy,
                clock=frozen,
                sleeper=sleeper,
                retryable=(_Boom,),
                correlation_id="rid-async",
                op="async-op",
            )
        )

    assert "RETRY_EXHAUSTED" in str(excinfo.value)
    assert excinfo.value.correlation_id == "rid-async"
    assert isinstance(excinfo.value.last_error, _Boom)
