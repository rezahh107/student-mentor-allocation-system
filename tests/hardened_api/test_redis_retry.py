import json
from typing import List

import pytest

from src.hardened_api.observability import get_metric
from src.hardened_api.redis_support import RedisExecutor, RedisOperationError, RedisRetryConfig


@pytest.mark.asyncio
async def test_redis_executor_backoff_and_metrics(caplog):
    config = RedisRetryConfig(attempts=3, base_delay=0.1, max_delay=0.4, jitter=0.1)
    delays: List[float] = []
    clock = {"value": 0.0}

    async def fake_sleep(value: float) -> None:
        delays.append(round(value, 3))
        clock["value"] += value

    def monotonic() -> float:
        return clock["value"]

    rng_values = iter([0.0, 0.5])

    def rng() -> float:
        return next(rng_values)

    attempts_metric = get_metric("redis_retry_attempts_total").labels(op="idem.test", outcome="error")
    exhausted_metric = get_metric("redis_retry_exhausted_total").labels(op="idem.test", outcome="error")
    latency_metric = get_metric("redis_operation_latency_seconds")

    before_attempts = attempts_metric._value.get()
    before_exhausted = exhausted_metric._value.get()

    def histogram_count(op: str) -> float:
        for sample in latency_metric.collect()[0].samples:
            if sample.name.endswith("_count") and sample.labels.get("op") == op:
                return sample.value
        return 0.0

    before_hist = histogram_count("idem.test")
    caplog.set_level("WARNING", logger="hardened_api.redis")

    async def failing_operation():
        raise TimeoutError("boom")

    executor = RedisExecutor(
        config=config,
        namespace="t:test",
        rng=rng,
        monotonic=monotonic,
        sleep=fake_sleep,
    )

    with pytest.raises(RedisOperationError):
        await executor.call(failing_operation, op_name="idem.test", correlation_id="rid-1")

    assert delays == [pytest.approx(0.1), pytest.approx(0.25)]

    after_attempts = attempts_metric._value.get()
    after_exhausted = exhausted_metric._value.get()
    after_hist = histogram_count("idem.test")

    assert after_attempts - before_attempts == 3
    assert after_exhausted - before_exhausted == 1
    assert after_hist - before_hist == 1

    matching = [json.loads(record.message) for record in caplog.records if record.name == "hardened_api.redis"]
    assert matching, "expected redis exhaustion log"
    log = matching[-1]
    assert log["event"] == "redis.retry_exhausted"
    assert log["op"] == "idem.test"
    assert log["rid"] == "rid-1"
    assert log["attempts"] == 3
    assert log["namespace"] == "t:test"


@pytest.mark.asyncio
async def test_fake_redis_ttl_parity(redis_client, frozen_clock):
    await redis_client.set("ttl-key", "value", ex=2)
    await frozen_clock.advance(1)
    assert await redis_client.get("ttl-key") is not None
    await frozen_clock.advance(2)
    assert await redis_client.get("ttl-key") is None
