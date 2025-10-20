from __future__ import annotations

import pytest

from sma.phase6_import_to_sabt.app.utils import get_debug_context
from sma.phase6_import_to_sabt.perf.harness import PerformanceHarness

pytestmark = pytest.mark.asyncio


async def test_p95_lt_200ms(async_client, service_metrics, deterministic_timer):
    harness = PerformanceHarness(metrics=service_metrics, timer=deterministic_timer)

    async def call_health():
        resp = await async_client.get("/healthz")
        assert resp.status_code == 200, get_debug_context(
            async_client.app, namespace="healthz", last_error=resp.text
        )

    async def call_ready():
        resp = await async_client.get("/readyz")
        assert resp.status_code in {200, 503}, get_debug_context(
            async_client.app, namespace="readyz", last_error=resp.text
        )

    await harness.run(call_health, iterations=5)
    await harness.run(call_ready, iterations=5)

    harness.assert_within_budget(0.2)
