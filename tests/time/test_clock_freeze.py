from __future__ import annotations

import asyncio
import json

from sma.hardened_api.redis_support import RedisExecutor, RedisNamespaces, RedisRetryConfig
from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.phase2_counter_service.counter_runtime import CounterRuntime
from sma.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics


class _DeterministicClock:
    def __init__(self) -> None:
        self._now = 1_000.0

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def monotonic(self) -> float:
        return self._now


class _PendingRedis:
    def __init__(self) -> None:
        self._invocations: list[int] = []
        self._called = 0

    async def eval(self, script: str, numkeys: int, *args):
        argv = args[numkeys:]
        ttl_ms = int(argv[-1])
        self._invocations.append(ttl_ms)
        self._called += 1
        if self._called == 1:
            return json.dumps({"status": "PENDING"})
        year_code = argv[1]
        prefix = argv[2]
        counter = f"{year_code}{prefix}0001"
        return json.dumps({"status": "NEW", "counter": counter, "serial": "0001"})

    async def get(self, name: str):
        return None


def test_backoff_and_ttl_without_wall_clock() -> None:
    async def _run() -> None:
        clock = _DeterministicClock()
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)
            clock.advance(delay)

        executor = RedisExecutor(
            config=RedisRetryConfig(attempts=2, base_delay=0.0, max_delay=0.0, jitter=0.0),
            namespace="counter-clock-test",
            rng=lambda: 0.0,
            monotonic=clock.monotonic,
            sleep=fake_sleep,
        )
        metrics = CounterRuntimeMetrics()
        redis = _PendingRedis()
        runtime = CounterRuntime(
            redis=redis,
            namespaces=RedisNamespaces("test-clock"),
            executor=executor,
            metrics=metrics,
            year_provider=AcademicYearProvider({"1402": "02"}),
            hash_salt="clock-test",
            wait_attempts=2,
            wait_base_ms=10,
            wait_max_ms=10,
        )

        result = await runtime.allocate(
            {"year": "1402", "gender": 1, "center": 1, "student_id": "clock-01"},
            correlation_id="clock",
        )
        assert result.counter.startswith("02")
        assert sleeps == [0.01]
        assert redis._invocations[-1] == runtime._placeholder_ttl  # type: ignore[attr-defined]

    asyncio.run(_run())
