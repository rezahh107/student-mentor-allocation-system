from __future__ import annotations

import asyncio

from sma.hardened_api.redis_support import RedisExecutor, RedisNamespaces, RedisRetryConfig
from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.phase2_counter_service.counter_runtime import CounterRuntime
from sma.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics
from sma.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX
from tests.hardened_api.conftest import FakeRedis


def test_counter_shape_matches_export_needs() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        executor = RedisExecutor(
            config=RedisRetryConfig(attempts=2, base_delay=0.0, max_delay=0.0, jitter=0.0),
            namespace="export-readiness",
        )
        runtime = CounterRuntime(
            redis=redis,
            namespaces=RedisNamespaces("export"),
            executor=executor,
            metrics=CounterRuntimeMetrics(),
            year_provider=AcademicYearProvider({"1402": "02"}),
            hash_salt="export",
        )

        result = await runtime.allocate(
            {"year": "1402", "gender": 0, "center": 1, "student_id": "EXPORT-001"},
            correlation_id="export",
        )
        assert COUNTER_PATTERN.fullmatch(result.counter)
        assert result.year_code == "02"
        assert result.counter.startswith("02" + COUNTER_PREFIX[0])

        preview = await runtime.preview({"year": "1402", "gender": "۰", "center": "۱"})
        assert COUNTER_PATTERN.fullmatch(preview.counter)

        await redis.flushdb()

    asyncio.run(_run())
