from __future__ import annotations

from src.reliability import ReliabilityMetrics


def _label_dicts(counter) -> list[dict[str, str]]:
    collected = counter.collect()[0]
    return [dict(sample.labels) for sample in collected.samples]


def test_retention_cleanup_chaos_metrics_labels() -> None:
    metrics = ReliabilityMetrics()
    metrics.mark_chaos(
        scenario="redis_export",
        incident_type="redis",
        outcome="fault",
        reason="injected_fault",
        namespace="obs",
    )
    metrics.mark_retention(mode="dry_run", reason="age", namespace="obs")
    metrics.mark_cleanup(kind="part_file", namespace="obs")

    chaos_labels = _label_dicts(metrics.chaos_incidents)
    assert any(
        label.get("outcome") == "fault"
        and label.get("type") == "redis"
        and label.get("reason") == "injected_fault"
        and label.get("namespace") == "obs"
        for label in chaos_labels
    )

    retention_labels = _label_dicts(metrics.retention_actions)
    assert any(
        label.get("mode") == "dry_run"
        and label.get("reason") == "age"
        and label.get("namespace") == "obs"
        for label in retention_labels
    )

    cleanup_labels = _label_dicts(metrics.cleanup_actions)
    assert any(
        label.get("kind") == "part_file" and label.get("namespace") == "obs"
        for label in cleanup_labels
    )
