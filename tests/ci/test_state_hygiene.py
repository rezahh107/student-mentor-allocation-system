from sma.phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_job_runner, make_row


def test_redis_and_registry_reset(tmp_path) -> None:
    runner, metrics = build_job_runner(tmp_path, [make_row(idx=1)])
    key = "phase6:test:state"
    runner.redis.setnx(key, "1")
    assert runner.redis.get(key) == "1"
    runner.redis.flushdb()
    assert runner.redis.get(key) is None

    metrics.errors_total.labels(type="validation", format="csv").inc()
    assert list(metrics.registry.collect()), "Metrics should have samples before reset"
    reset_registry(metrics.registry)
    assert list(metrics.registry.collect()) == []
