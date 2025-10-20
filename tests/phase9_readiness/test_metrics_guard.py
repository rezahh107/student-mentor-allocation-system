from __future__ import annotations

import asyncio

import httpx
import pytest

from sma.phase9_readiness.http_app import create_readiness_app


@pytest.mark.usefixtures("frozen_time")
def test_metrics_token_guard_persists(metrics, env_config, clock):
    metrics.uat_plan_runs.labels(outcome="success", namespace=env_config.namespace).inc()
    app = create_readiness_app(metrics=metrics, env_config=env_config, clock=clock)

    async def run_checks() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            forbidden = await client.get("/metrics")
            assert forbidden.status_code == 401
            assert "توکن" in forbidden.json()["detail"]

            allowed = await client.get(
                "/metrics",
                headers={"Authorization": f"Bearer {env_config.tokens.metrics_read}"},
            )
            assert allowed.status_code == 200
            assert "uat_plan_runs_total" in allowed.text
            assert allowed.headers["X-Middleware-Order"].split(",") == [
                "RateLimit",
                "Idempotency",
                "Auth",
            ]

            ready = await client.get(
                "/readyz",
                headers={"Authorization": f"Bearer {env_config.tokens.metrics_read}"},
            )
            assert ready.status_code == 200
            assert ready.headers["X-Middleware-Order"].split(",") == [
                "RateLimit",
                "Idempotency",
                "Auth",
            ]

    asyncio.run(run_checks())
