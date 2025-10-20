from __future__ import annotations

import asyncio
import uuid

import httpx

from sma.hardened_api.observability import get_metric, metrics_registry_guard
from tests.hardened_api.conftest import build_counter_app


def test_metrics_success_path_allowed() -> None:
    async def _run() -> None:
        with metrics_registry_guard():
            app, redis_client = build_counter_app(
                namespace=f"metrics-allow-{uuid.uuid4()}",
                metrics_token="secret-token",
                metrics_ip_allowlist=["testserver", "127.0.0.1"],
            )
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            headers = {
                "Authorization": "Bearer secret-token",
                "X-API-Key": "STATICKEY1234567890",
            }
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.get("/metrics", headers=headers)
                    assert response.status_code == 200, response.text
                    payload = response.text
                    assert "counter_alloc_total" in payload
                scrape_metric = get_metric("metrics_scrape_total")
                samples = [
                    sample
                    for metric in scrape_metric.collect()
                    for sample in metric.samples
                    if sample.name.endswith("_total")
                ]
                assert any(
                    sample.labels.get("outcome") == "success" and sample.value >= 1
                    for sample in samples
                )
                assert not any(sample.labels.get("outcome") == "token_denied" for sample in samples)
            finally:
                await redis_client.flushdb()
                await transport.aclose()

    asyncio.run(_run())
