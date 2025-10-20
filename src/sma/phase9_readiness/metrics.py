from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class ReadinessMetrics:
    """Prometheus metrics exposed by the phase-9 automation."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.uat_plan_runs = Counter(
            "uat_plan_runs_total",
            "Number of UAT plan generations by outcome.",
            labelnames=("outcome", "namespace"),
            registry=self.registry,
        )
        self.pilot_runs = Counter(
            "pilot_runs_total",
            "Pilot executions grouped by outcome.",
            labelnames=("outcome", "namespace"),
            registry=self.registry,
        )
        self.bluegreen_rollbacks = Counter(
            "bluegreen_rollbacks_total",
            "Count of blue/green rollback events.",
            labelnames=("outcome", "namespace"),
            registry=self.registry,
        )
        self.backup_restore_runs = Counter(
            "backup_restore_runs_total",
            "Backup and restore stage outcomes.",
            labelnames=("stage", "outcome", "namespace"),
            registry=self.registry,
        )
        self.retries = Counter(
            "phase9_retry_total",
            "Total retries performed grouped by operation.",
            labelnames=("operation", "namespace"),
            registry=self.registry,
        )
        self.retry_exhaustions = Counter(
            "phase9_retry_exhausted_total",
            "Count of retry loops that exhausted all attempts.",
            labelnames=("operation", "namespace"),
            registry=self.registry,
        )
        self.stage_duration = Histogram(
            "phase9_stage_duration_seconds",
            "Duration histogram for phase-9 operations.",
            labelnames=("stage",),
            registry=self.registry,
            buckets=(
                0.01,
                0.05,
                0.1,
                0.2,
                0.5,
                1.0,
                2.0,
                5.0,
                10.0,
                30.0,
            ),
        )

    def mark_retry(self, *, operation: str, namespace: str) -> None:
        self.retries.labels(operation=operation, namespace=namespace).inc()

    def mark_retry_exhausted(self, *, operation: str, namespace: str) -> None:
        self.retry_exhaustions.labels(operation=operation, namespace=namespace).inc()

    def observe_duration(self, *, stage: str, seconds: float) -> None:
        self.stage_duration.labels(stage=stage).observe(max(0.0, seconds))


__all__ = ["ReadinessMetrics"]
