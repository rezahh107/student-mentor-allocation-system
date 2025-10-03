import uuid

import pytest

from src.hardened_api.observability import get_metric
from src.hardened_api.redis_support import RedisOperationError
from tests.hardened_api.conftest import setup_test_data

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_rate_limit_and_idem_retry_buckets_present(client, clean_state):
    rate_metric = get_metric("rate_limit_events_total")
    idem_metric = get_metric("idempotency_events_total")

    original_limiter = client.app.state.middleware_state.rate_limiter

    class _FailOpenLimiter:
        async def allow(self, *args, **kwargs):  # pragma: no cover - simple stub
            raise RedisOperationError("unavailable")

    client.app.state.middleware_state.rate_limiter = _FailOpenLimiter()
    try:
        resp = await client.get(
            "/status",
            headers={"Authorization": "Bearer TESTTOKEN1234567890"},
        )
    finally:
        client.app.state.middleware_state.rate_limiter = original_limiter
    assert resp.status_code == 200
    assert (
        rate_metric.labels(op="GET", endpoint="/status", outcome="fail_open", reason="redis_unavailable")._value.get()
        == 1
    )

    class _FailClosedLimiter:
        async def allow(self, *args, **kwargs):  # pragma: no cover - simple stub
            raise RedisOperationError("offline")

    client.app.state.middleware_state.rate_limiter = _FailClosedLimiter()
    payload = setup_test_data(f"{uuid.uuid4().int % 1_000_000:06d}")
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Idempotency-Key": f"idem-hist-fail-{uuid.uuid4().hex[:10]}",
        "Content-Type": "application/json; charset=utf-8",
    }
    failure = await client.post("/allocations", json=payload, headers=headers)
    client.app.state.middleware_state.rate_limiter = original_limiter
    assert failure.status_code == 500
    assert (
        rate_metric.labels(op="POST", endpoint="/allocations", outcome="error", reason="redis_unavailable")._value.get()
        == 1
    )

    headers["Idempotency-Key"] = f"idem-hist-pass-{uuid.uuid4().hex[:10]}"
    success = await client.post("/allocations", json=payload, headers=headers)
    assert success.status_code == 200
    assert (
        idem_metric.labels(op="POST", endpoint="/allocations", outcome="committed", reason="completed")._value.get()
        >= 1
    )

    histogram = get_metric("redis_operation_latency_seconds")
    samples = histogram.collect()[0].samples
    reserve_buckets = [
        sample for sample in samples if sample.name.endswith("_bucket") and sample.labels.get("op") == "idempotency.reserve"
    ]
    assert any(sample.value > 0 for sample in reserve_buckets)
    ratelimit_buckets = [
        sample
        for sample in samples
        if sample.name.endswith("_bucket") and sample.labels.get("op", "").startswith("ratelimit.")
    ]
    assert ratelimit_buckets and any(sample.value > 0 for sample in ratelimit_buckets)
