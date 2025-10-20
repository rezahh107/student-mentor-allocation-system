from __future__ import annotations

import asyncio
import json
import logging
from hashlib import blake2s

import pytest
from prometheus_client import CollectorRegistry

from sma.hardened_api.redis_support import RedisExecutor, RedisNamespaces, RedisRetryConfig
from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.phase2_counter_service.counter_runtime import CounterRuntime, CounterRuntimeError
from sma.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics


class _ScriptStubRedis:
    def __init__(self) -> None:
        self._calls = 0

    async def eval(self, script: str, numkeys: int, *args):
        keys = args[:numkeys]
        argv = args[numkeys:]
        self._calls += 1
        if self._calls == 1:
            return json.dumps({"status": "PENDING"})
        year_code = argv[1]
        prefix = argv[2]
        counter = f"{year_code}{prefix}0001"
        return json.dumps({"status": "NEW", "counter": counter, "serial": "0001"})

    async def get(self, name: str):
        return None


def test_retry_exhaustion_metrics_and_masking(caplog) -> None:
    async def _run() -> None:
        registry = CollectorRegistry()
        metrics = CounterRuntimeMetrics(registry)
        namespaces = RedisNamespaces("test-counter-metrics")
        retry_config = RedisRetryConfig(attempts=2, base_delay=0.0, max_delay=0.0, jitter=0.0)
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        executor = RedisExecutor(
            config=retry_config,
            namespace="test-counter-metrics",
            rng=lambda: 0.0,
            monotonic=lambda: 0.0,
            sleep=fake_sleep,
        )
        runtime = CounterRuntime(
            redis=_ScriptStubRedis(),
            namespaces=namespaces,
            executor=executor,
            metrics=metrics,
            year_provider=AcademicYearProvider({"1402": "02"}),
            hash_salt="pepper",
            wait_attempts=2,
            wait_base_ms=10,
            wait_max_ms=20,
        )

        payload = {"year": "1402", "gender": 0, "center": 1, "student_id": "STU-۹۸۷"}
        with caplog.at_level(logging.INFO):
            result = await runtime.allocate(payload, correlation_id="corr-1")

        assert result.counter.startswith("02")
        hashed = blake2s(key=b"pepper", digest_size=16)
        hashed.update("STU-۹۸۷".encode("utf-8"))
        digest = hashed.hexdigest()
        assert digest in caplog.text
        assert "STU-۹۸۷" not in caplog.text
        assert sleeps == [0.01]

        retry_value = registry.get_sample_value("counter_retry_total", {"operation": "counter_allocate"})
        assert retry_value == 2.0

        runtime._max_serial = 0  # type: ignore[attr-defined]
        with pytest.raises(CounterRuntimeError) as excinfo:
            await runtime.preview({"year": "1402", "gender": "۰", "center": "۱"})
        assert excinfo.value.code == "COUNTER_EXHAUSTED"

        exhausted_value = registry.get_sample_value("counter_exhausted_total", {"year_code": "02", "gender": "0"})
        assert exhausted_value == 1.0

    asyncio.run(_run())
