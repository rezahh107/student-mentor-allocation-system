from __future__ import annotations

from typing import List

from prometheus_client import CollectorRegistry

from sma._local_fakeredis import FakeStrictRedis
from sma.core.retry import retry_attempts_total, retry_exhaustion_total
from sma.testing.state import get_test_namespace

_SENTINELS: List[str] = []


def test_namespaces_cleanup_between_tests(rid: str) -> None:
    namespace = get_test_namespace()
    client = FakeStrictRedis()
    sentinel_key = f"{namespace}:sentinel"
    client.set(sentinel_key, rid)
    _SENTINELS.append(sentinel_key)

    assert rid.startswith("rid-"), "Correlation-ID must be deterministic"
    assert client.get(sentinel_key) == rid.encode("utf-8")


def test_namespaces_cleanup_between_tests_followup(rid: str) -> None:
    namespace = get_test_namespace()
    client = FakeStrictRedis()

    for key in _SENTINELS:
        assert client.get(key) is None, f"Expected {key} to be flushed for namespace={namespace}"

    # Record fresh state for any additional verifications
    client.set(f"{namespace}:check", rid)
    assert client.get(f"{namespace}:check") == rid.encode("utf-8")


def test_prometheus_registry_starts_clean(fresh_metrics_registry: CollectorRegistry) -> None:
    attempts_metrics = retry_attempts_total.collect()
    exhaustion_metrics = retry_exhaustion_total.collect()

    for metric in (*attempts_metrics, *exhaustion_metrics):
        for sample in metric.samples:
            assert sample.value == 0.0, f"Metric {metric.name} not reset; sample={sample}"

    # Registry injected by fixture should match provided CollectorRegistry instance
    assert fresh_metrics_registry is not None

