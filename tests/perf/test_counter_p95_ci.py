from __future__ import annotations

import asyncio
import json
import time

from src.hardened_api.redis_support import RedisExecutor, RedisNamespaces, RedisRetryConfig
from src.phase2_counter_service.academic_year import AcademicYearProvider
from src.phase2_counter_service.counter_runtime import CounterRuntime
from src.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics


class _FastRedis:
    async def eval(self, script: str, numkeys: int, *args):
        argv = args[numkeys:]
        year_code = argv[1]
        prefix = argv[2]
        serial = "0001"
        counter = f"{year_code}{prefix}{serial}"
        return json.dumps({"status": "NEW", "counter": counter, "serial": serial})

    async def get(self, name: str):
        return b"0"


def test_p95_under_budget() -> None:
    async def _run() -> None:
        async def no_sleep(_: float) -> None:
            return None

        executor = RedisExecutor(
            config=RedisRetryConfig(attempts=1, base_delay=0.0, max_delay=0.0, jitter=0.0),
            namespace="counter-perf",
            rng=lambda: 0.0,
            monotonic=time.perf_counter,
            sleep=no_sleep,
        )
        runtime = CounterRuntime(
            redis=_FastRedis(),
            namespaces=RedisNamespaces("perf-counter"),
            executor=executor,
            metrics=CounterRuntimeMetrics(),
            year_provider=AcademicYearProvider({"1402": "02"}),
            hash_salt="perf",
            wait_attempts=1,
        )

        durations: list[float] = []
        for idx in range(50):
            start = time.perf_counter()
            await runtime.allocate(
                {"year": "1402", "gender": 0, "center": 1, "student_id": f"perf-{idx}"},
                correlation_id=f"perf-{idx}",
            )
            durations.append(time.perf_counter() - start)

        durations.sort()
        cutoff_index = int(len(durations) * 0.95) - 1
        cutoff_index = max(cutoff_index, 0)
        p95 = durations[cutoff_index]
        assert p95 <= 0.12

    asyncio.run(_run())
