from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class ExporterMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.jobs_total = Counter(
            "export_jobs_total",
            "Total export jobs by status",
            labelnames=("status",),
            registry=self.registry,
        )
        self.duration_seconds = Histogram(
            "export_duration_seconds",
            "Export durations by phase",
            labelnames=("phase",),
            registry=self.registry,
        )
        self.rows_total = Counter(
            "export_rows_total",
            "Rows exported",
            registry=self.registry,
            labelnames=("format",),
        )
        self.file_bytes_total = Counter(
            "export_file_bytes_total",
            "Bytes written per export",
            registry=self.registry,
            labelnames=("format",),
        )
        self.errors_total = Counter(
            "export_errors_total",
            "Export errors",
            labelnames=("type",),
            registry=self.registry,
        )

    def observe_rows(self, rows: int, *, format: str = "csv") -> None:
        self.rows_total.labels(format=format).inc(rows)

    def observe_file_bytes(self, size: int, *, format: str = "csv") -> None:
        self.file_bytes_total.labels(format=format).inc(size)

    def inc_job(self, status: str) -> None:
        self.jobs_total.labels(status=status).inc()

    def observe_duration(self, phase: str, seconds: float) -> None:
        self.duration_seconds.labels(phase=phase).observe(seconds)

    def inc_error(self, error_type: str) -> None:
        self.errors_total.labels(type=error_type).inc()
