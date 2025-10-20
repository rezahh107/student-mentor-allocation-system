from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class ReliabilityMetrics:
    """Prometheus metrics registry for reliability tooling."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.chaos_incidents = Counter(
            "chaos_incidents_total",
            "Number of chaos incidents injected by type.",
            labelnames=("type", "scenario", "outcome", "reason", "namespace"),
            registry=self.registry,
        )
        self.retention_actions = Counter(
            "retention_actions_total",
            "Retention operations performed grouped by mode.",
            labelnames=("mode", "reason", "namespace"),
            registry=self.registry,
        )
        self.cleanup_actions = Counter(
            "cleanup_actions_total",
            "Cleanup operations executed by kind.",
            labelnames=("kind", "namespace"),
            registry=self.registry,
        )
        self.dr_runs = Counter(
            "dr_runs_total",
            "Disaster recovery drill runs aggregated by status.",
            labelnames=("status", "namespace"),
            registry=self.registry,
        )
        self.dr_bytes = Counter(
            "dr_bytes_total",
            "Total bytes processed during DR drills.",
            labelnames=("direction", "namespace"),
            registry=self.registry,
        )
        self.durations = Histogram(
            "reliability_duration_seconds",
            "Duration histogram for reliability operations.",
            labelnames=("component",),
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
        )
        self.inflight_backups = Gauge(
            "dr_inflight_backups",
            "Current number of backups running.",
            registry=self.registry,
        )
        self.retries = Counter(
            "reliability_retry_total",
            "Total retries performed grouped by operation.",
            labelnames=("operation", "namespace"),
            registry=self.registry,
        )
        self.exhaustions = Counter(
            "reliability_exhaustion_total",
            "Total times an operation exhausted its retries.",
            labelnames=("operation", "namespace"),
            registry=self.registry,
        )
        self.operations = Counter(
            "reliability_operations_total",
            "Reliability operation outcomes.",
            labelnames=("operation", "outcome", "reason", "namespace"),
            registry=self.registry,
        )

    def observe_duration(self, component: str, seconds: float) -> None:
        self.durations.labels(component=component).observe(max(0.0, seconds))

    def mark_chaos(
        self,
        *,
        scenario: str,
        incident_type: str,
        outcome: str,
        reason: str,
        namespace: str,
    ) -> None:
        self.chaos_incidents.labels(
            type=incident_type,
            scenario=scenario,
            outcome=outcome,
            reason=reason,
            namespace=namespace,
        ).inc()

    def mark_retention(self, *, mode: str, reason: str, namespace: str) -> None:
        self.retention_actions.labels(mode=mode, reason=reason, namespace=namespace).inc()

    def mark_cleanup(self, *, kind: str, namespace: str) -> None:
        self.cleanup_actions.labels(kind=kind, namespace=namespace).inc()

    def mark_dr(self, *, status: str, namespace: str) -> None:
        self.dr_runs.labels(status=status, namespace=namespace).inc()

    def add_dr_bytes(self, *, direction: str, amount: int, namespace: str) -> None:
        self.dr_bytes.labels(direction=direction, namespace=namespace).inc(max(0, amount))

    def mark_retry(self, *, operation: str, namespace: str) -> None:
        self.retries.labels(operation=operation, namespace=namespace).inc()

    def mark_exhausted(self, *, operation: str, namespace: str) -> None:
        self.exhaustions.labels(operation=operation, namespace=namespace).inc()

    def mark_operation(self, *, operation: str, outcome: str, reason: str, namespace: str) -> None:
        self.operations.labels(
            operation=operation,
            outcome=outcome,
            reason=reason,
            namespace=namespace,
        ).inc()


__all__ = ["ReliabilityMetrics"]
