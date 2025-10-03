from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client import CollectorRegistry

from core.retry import retry_attempts_total, retry_backoff_seconds, retry_exhaustion_total
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.exporter_service import atomic_writer
from phase6_import_to_sabt.obs.metrics import build_metrics


def test_registry_reset_and_namespaces(tmp_path: Path) -> None:
    registry = CollectorRegistry()
    metrics = build_metrics("import_to_sabt_state_retry", registry=registry)

    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()

    metrics.retry_attempts_total.labels(operation="ratelimit", route="/api/jobs").inc()
    metrics.retry_backoff_seconds.labels(operation="ratelimit", route="/api/jobs").observe(0.05)
    retry_attempts_total.labels(op="phase6.test", outcome="retry").inc()
    retry_backoff_seconds.labels(op="phase6.test").observe(0.05)

    assert any(sample.value for metric in registry.collect() for sample in metric.samples)
    metrics.reset()
    assert all(sample.value == 0 for metric in registry.collect() for sample in metric.samples)

    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    store = InMemoryKeyValueStore("state:hygiene", clock)

    async def _exercise() -> None:
        await store.set("demo", "payload", ttl_seconds=60)
        await store.delete("demo")

    asyncio.run(_exercise())
    assert not store._store

    target = tmp_path / "artifact.csv"
    with atomic_writer(target) as handle:
        handle.write("value")
    assert target.exists()
    assert not list(tmp_path.glob("*.part"))

    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()
