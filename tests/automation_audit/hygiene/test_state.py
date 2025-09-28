from prometheus_client import CollectorRegistry

from automation_audit.idem import IdempotencyStore
from automation_audit.metrics import build_metrics


def test_redis_clean(redis_client):
    redis_client.set("x", "1")
    redis_client.flushall()
    assert redis_client.dbsize() == 0


def test_prom_registry_reset(metrics_registry):
    metrics = build_metrics(metrics_registry)
    metrics.audit_runs.inc()
    assert isinstance(metrics.registry, CollectorRegistry)


def test_unique_namespace(redis_client):
    first = IdempotencyStore(redis_client, namespace="automation_audit:idemp:first")
    second = IdempotencyStore(redis_client, namespace="automation_audit:idemp:second")
    first.put_if_absent("key", {"value": 1})
    assert second.get("key") is None
