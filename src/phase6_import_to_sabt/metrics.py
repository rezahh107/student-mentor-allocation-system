from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class ExporterMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.jobs_total = Counter(
            "export_jobs_total",
            "Total export jobs by status",
            labelnames=("status", "format"),
            registry=self.registry,
        )
        self.duration_seconds = Histogram(
            "export_duration_seconds",
            "Export durations by phase",
            labelnames=("phase", "format"),
            registry=self.registry,
        )
        self.rows_total = Counter(
            "export_rows_total",
            "Rows exported",
            labelnames=("format",),
            registry=self.registry,
        )
        self.file_bytes_total = Counter(
            "export_file_bytes_total",
            "Bytes written per export",
            labelnames=("format",),
            registry=self.registry,
        )
        self.errors_total = Counter(
            "export_errors_total",
            "Export errors",
            labelnames=("type", "format"),
            registry=self.registry,
        )
        self.rate_limit_total = Counter(
            "export_rate_limit_total",
            "Rate limit decisions for export API",
            labelnames=("outcome", "reason"),
            registry=self.registry,
        )

    def observe_rows(self, rows: int, format_label: str) -> None:
        self.rows_total.labels(format=format_label).inc(rows)

    def observe_file_bytes(self, size: int, format_label: str) -> None:
        self.file_bytes_total.labels(format=format_label).inc(size)

    def inc_job(self, status: str, format_label: str) -> None:
        self.jobs_total.labels(status=status, format=format_label).inc()

    def observe_duration(self, phase: str, seconds: float, format_label: str) -> None:
        self.duration_seconds.labels(phase=phase, format=format_label).observe(seconds)

    def inc_error(self, error_type: str, format_label: str) -> None:
        self.errors_total.labels(type=error_type, format=format_label).inc()

    def inc_rate_limit(self, *, outcome: str, reason: str) -> None:
        self.rate_limit_total.labels(outcome=outcome, reason=reason).inc()


def reset_registry(registry: CollectorRegistry) -> None:
    """Completely clear a CollectorRegistry between tests.

    The prometheus_client Registry keeps internal mappings that need explicit
    teardown to avoid metric name collisions across parametrized test runs.
    """

    collectors = list(getattr(registry, "_collector_to_names", {}).keys())
    for collector in collectors:
        try:
            registry.unregister(collector)
        except KeyError:
            continue
    names = getattr(registry, "_names_to_collectors", None)
    if isinstance(names, dict):
        names.clear()


__all__ = ["ExporterMetrics", "reset_registry"]
