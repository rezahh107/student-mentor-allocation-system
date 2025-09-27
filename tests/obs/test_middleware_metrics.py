from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _get_counter_value(metric, **labels) -> float:
    collection = metric.collect()[0].samples
    for sample in collection:
        if all(sample.labels.get(k) == v for k, v in labels.items()):
            return sample.value
    return 0.0


async def test_rate_limit_metrics(async_client, service_metrics):
    headers = {
        "Authorization": "Bearer service-token",
        "Idempotency-Key": "rl-test",
        "X-Client-ID": "tenant",
    }
    first = await async_client.post("/api/jobs", headers=headers)
    second = await async_client.post("/api/jobs", headers=headers)
    third = await async_client.post("/api/jobs", headers=headers)
    assert third.status_code == 429
    blocked = _get_counter_value(service_metrics.middleware.rate_limit_decision_total, decision="block")
    assert blocked >= 1


async def test_idempotency_hit_miss_metrics(async_client, service_metrics):
    headers = {
        "Authorization": "Bearer service-token",
        "Idempotency-Key": "idem-test",
        "X-Client-ID": "tenant",
    }
    first = await async_client.post("/api/jobs", headers=headers)
    second = await async_client.post("/api/jobs", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    miss = _get_counter_value(service_metrics.middleware.idempotency_hits_total, outcome="miss")
    hit = _get_counter_value(service_metrics.middleware.idempotency_hits_total, outcome="hit")
    assert miss >= 1
    assert hit >= 1
    assert service_metrics.middleware.idempotency_replays_total._value.get() >= 1  # type: ignore[attr-defined]
