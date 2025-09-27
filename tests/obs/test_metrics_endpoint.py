from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_metrics_requires_token(async_client):
    unauthorized = await async_client.get("/metrics")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["fa_error_envelope"]["code"] == "METRICS_TOKEN_INVALID"
    authorized = await async_client.get("/metrics", headers={"X-Metrics-Token": "token123"})
    assert authorized.status_code == 200
    assert "rate_limit_decision_total" in authorized.text
