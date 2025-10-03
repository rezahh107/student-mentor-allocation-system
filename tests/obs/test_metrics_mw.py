import uuid

import pytest

from src.hardened_api.observability import get_metric
from tests.hardened_api.conftest import setup_test_data

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_retry_exhaustion_metrics_present(client, clean_state):
    suffix = f"{uuid.uuid4().int % 1_000_000:06d}"
    payload = setup_test_data(suffix)
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Idempotency-Key": f"idem:metrics:{uuid.uuid4().hex[:12]}",
        "Content-Type": "application/json; charset=utf-8",
    }

    first = await client.post("/allocations", json=payload, headers=headers)
    assert first.status_code == 200, first.text

    second = await client.post("/allocations", json=payload, headers=headers)
    assert second.status_code == 409, second.text

    rate_metric = get_metric("rate_limit_events_total")
    allowed = rate_metric.labels(op="POST", endpoint="/allocations", outcome="allowed", reason="ok")._value.get()
    assert allowed >= 1

    idempotency_metric = get_metric("idempotency_events_total")
    reserved = idempotency_metric.labels(op="POST", endpoint="/allocations", outcome="reserved", reason="inflight")._value.get()
    replay = idempotency_metric.labels(op="POST", endpoint="/allocations", outcome="replay", reason="completed")._value.get()
    assert reserved >= 1
    assert replay >= 1

    retry_metric = get_metric("redis_retry_attempts_total")
    reserve_attempts = retry_metric.labels(op="idempotency.reserve", outcome="success")._value.get()
    assert reserve_attempts >= 1
