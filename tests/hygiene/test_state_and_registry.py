from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_state_cleanup_isolation(async_client, service_metrics, deterministic_timer):
    await async_client.get("/healthz")
    await async_client.post(
        "/api/jobs",
        headers={
            "Authorization": "Bearer service-token",
            "Idempotency-Key": "cleanup-key",
            "X-Client-ID": "tenant",
        },
    )
    assert deterministic_timer.recorded
    service_metrics.reset()
    assert list(service_metrics.registry.collect()) == []
    deterministic_timer.recorded.clear()
    assert deterministic_timer.recorded == []
