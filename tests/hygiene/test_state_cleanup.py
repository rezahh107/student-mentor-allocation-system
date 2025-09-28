from __future__ import annotations

import asyncio

from src.hardened_api.observability import get_metric, metrics_registry_guard
from tests.hardened_api.conftest import FakeRedis


def test_redis_and_registry_reset() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        await redis.set("test:key", "value")
        assert await redis.get("test:key") is not None
        await redis.flushdb()
        assert await redis.get("test:key") is None

        with metrics_registry_guard():
            metric = get_metric("redis_retry_attempts_total")
            metric.labels(op="guard-test", outcome="success").inc()
            samples = metric.collect()[0].samples
            recorded = [s.value for s in samples if s.labels.get("op") == "guard-test"]
            assert recorded and recorded[0] == 1.0

        post_samples = metric.collect()[0].samples
        after = [s.value for s in post_samples if s.labels.get("op") == "guard-test"]
        assert not after or after[0] == 0.0

    asyncio.run(_run())
