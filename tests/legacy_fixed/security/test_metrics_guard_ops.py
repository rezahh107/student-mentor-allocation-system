from __future__ import annotations

import asyncio
import uuid

import httpx

from sma.hardened_api.observability import metrics_registry_guard
from tests.hardened_api.conftest import build_counter_app


def test_metrics_requires_token() -> None:
    async def _run() -> None:
        with metrics_registry_guard():
            app, redis = build_counter_app(
                namespace=f"test-{uuid.uuid4()}",
                metrics_token="secret-token",
                metrics_ip_allowlist=["testserver", "127.0.0.1"],
            )
            transport = httpx.ASGITransport(app=app)
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    unauthorized = await client.get("/metrics")
                    assert unauthorized.status_code == 401
                    denied = await client.get(
                        "/metrics",
                        headers={"Authorization": "Bearer secret-token"},
                    )
                    assert denied.status_code == 401
            finally:
                await redis.flushdb()
                await transport.aclose()

    asyncio.run(_run())
