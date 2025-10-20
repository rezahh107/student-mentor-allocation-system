from __future__ import annotations

import asyncio
import math
import time
import uuid

import httpx
import pytest
from redis.asyncio import Redis

from sma.hardened_api.middleware import (
    ensure_rate_limit_config_restored,
    restore_rate_limit_config,
    snapshot_rate_limit_config,
)
from tests.hardened_api.conftest import build_counter_app, get_debug_context, verify_middleware_order
from tests.hardened_api.redis_launcher import RedisLaunchSkipped, launch_redis_server


@pytest.mark.performance
def test_p95_under_budget_real_redis() -> None:
    async def _run() -> None:
        try:
            with launch_redis_server() as runtime:
                redis_client = Redis.from_url(runtime.url, encoding="utf-8", decode_responses=False)
                namespace = f"perf-real:{uuid.uuid4()}"
                await redis_client.flushdb()
                app, _ = build_counter_app(
                    namespace=namespace,
                    metrics_ip_allowlist=["testserver", "127.0.0.1"],
                    redis_client=redis_client,
                    settings_overrides={
                        "redis_url": runtime.url,
                        "redis_namespace": namespace,
                        "counter_year_map": {"1402": "02"},
                        "rate_limit_allocations": 200,
                        "rate_limit_window": 1.0,
                    },
                )
                verify_middleware_order(app)
                config = app.state.middleware_state.rate_limit_config  # type: ignore[attr-defined]
                snapshot = snapshot_rate_limit_config(config)
                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                headers = {
                    "Content-Type": "application/json; charset=utf-8",
                    "X-API-Key": "STATICKEY1234567890",
                }
                durations: list[float] = []
                warmup = 5
                samples = 40
                try:
                    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                        setattr(client, "app", app)
                        for idx in range(warmup + samples):
                            payload = {
                                "year": "1402",
                                "gender": 1,
                                "center": 1,
                                "student_id": f"perf-real-{idx}",
                            }
                            headers["Idempotency-Key"] = f"PERFKEY{idx:08d}AB"
                            start = time.perf_counter()
                            response = await client.post(
                                "/counter/allocate",
                                headers=headers,
                                json=payload,
                            )
                            assert response.status_code == 200, get_debug_context(client.app)
                            durations.append(time.perf_counter() - start)
                finally:
                    try:
                        ensure_rate_limit_config_restored(
                            config,
                            snapshot,
                            context="test_p95_under_budget_real_redis",
                        )
                    finally:
                        restore_rate_limit_config(config, snapshot)
                    await transport.aclose()
                    await redis_client.flushdb()
                    await redis_client.aclose()
                measured = durations[warmup:]
                measured.sort()
                index = max(0, math.ceil(len(measured) * 0.95) - 1)
                p95 = measured[index] if measured else 0.0
                assert p95 <= 0.12, f"p95 latency {p95:.6f}s exceeded budget"
        except RedisLaunchSkipped as exc:
            pytest.fail(f"Redis server unavailable: {exc}")

    asyncio.run(_run())
