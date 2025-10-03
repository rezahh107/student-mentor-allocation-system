from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from prometheus_client import CollectorRegistry, REGISTRY

from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.obs.metrics import build_metrics


pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestRemovedIn9Warning")


def test_redis_db_tmp_cleaned_and_collector_registry_reset() -> None:
    baseline = {metric.name for metric in REGISTRY.collect()}
    registry = CollectorRegistry()
    metrics = build_metrics("import_to_sabt_state_test", registry=registry)
    metrics.request_total.labels(method="GET", path="/healthz", status="200").inc()
    assert {metric.name for metric in REGISTRY.collect()} == baseline

    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    store = InMemoryKeyValueStore("state:hygiene", clock)

    async def _exercise() -> None:
        await store.incr("rate", ttl_seconds=10)
        await store.delete("rate")

    asyncio.run(_exercise())
    assert not store._store

