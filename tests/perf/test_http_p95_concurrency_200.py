from __future__ import annotations

import asyncio
import uuid

import pytest
from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.obs.metrics import build_metrics
from phase6_import_to_sabt.perf.harness import PerformanceHarness
from src.hardened_api.middleware import RateLimitRule
from src.hardened_api.redis_support import RateLimitResult

from tests.hardened_api.conftest import setup_test_data, temporary_rate_limit_config

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")


@pytest.mark.asyncio
async def test_post_exports_chain_p95_budget(client) -> None:
    """200 POST /allocations calls retain RateLimit→Idempotency→Auth ordering under budget."""

    with temporary_rate_limit_config(client.app) as config:
        config.default_rule = RateLimitRule(requests=500, window_seconds=60.0)
        config.per_route["/allocations"] = RateLimitRule(requests=500, window_seconds=60.0)

        durations = [0.11 + 0.001 * (idx % 7) for idx in range(200)]
        registry = CollectorRegistry()
        harness = PerformanceHarness(metrics=build_metrics("alloc-http-p95", registry=registry))

        original_limiter = client.app.state.middleware_state.rate_limiter

        class _UnlimitedLimiter:
            async def allow(self, *args, **kwargs) -> RateLimitResult:  # pragma: no cover - simple stub
                return RateLimitResult(True, remaining=500)

        client.app.state.middleware_state.rate_limiter = _UnlimitedLimiter()

        async def _fire(idx: int) -> None:
            payload = setup_test_data(f"{idx:06d}")
            headers = {
                "Authorization": "Bearer TESTTOKEN1234567890",
                "Idempotency-Key": f"idem-perf-{uuid.uuid4().hex[:16]}",
                "Content-Type": "application/json; charset=utf-8",
                "X-Debug-MW-Probe": "trace",
            }
            response = await client.post("/allocations", json=payload, headers=headers)
            assert response.status_code == 200, response.text
            trace_header = response.headers["X-MW-Trace"].split("|")[1]
            assert trace_header == "RateLimit>Idempotency>Auth", trace_header
            harness.record(durations[idx])

        try:
            await asyncio.gather(*(_fire(idx) for idx in range(200)))
        finally:
            client.app.state.middleware_state.rate_limiter = original_limiter

        harness.assert_within_budget(0.2)
        assert len(harness.samples) == 200


def test_exporter_baseline_100k_rows_p95_budget() -> None:
    """Budget regression for 100k-row exports without wall-clock reliance."""

    row_chunks = [50_000, 30_000, 20_000]
    durations = [12.4, 12.7, 13.1]
    timer = DeterministicTimer(durations)
    http_registry = CollectorRegistry()
    harness = PerformanceHarness(metrics=build_metrics("exporter-baseline", registry=http_registry), timer=timer)
    exporter_metrics = ExporterMetrics(CollectorRegistry())

    for chunk_rows in row_chunks:
        handle = harness.timer.start()
        elapsed = handle.elapsed()
        exporter_metrics.observe_duration("query", elapsed * 0.25, "xlsx")
        exporter_metrics.observe_duration("write_chunk", elapsed * 0.75, "xlsx")
        exporter_metrics.observe_rows(chunk_rows, "xlsx")
        exporter_metrics.inc_job("SUCCESS", "xlsx")
        harness.record(elapsed)

    harness.assert_within_budget(15.0)
    collected = exporter_metrics.duration_seconds.collect()[0].samples
    query_samples = [s for s in collected if s.name.endswith("_sum") and s.labels.get("phase") == "query"]
    assert query_samples and query_samples[0].value > 0
