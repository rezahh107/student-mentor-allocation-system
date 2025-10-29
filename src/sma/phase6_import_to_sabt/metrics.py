from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class ExporterMetrics:
    """Prometheus metrics wrapper for ImportToSabt exporter pipeline."""

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
            "Bytes written per export file",
            labelnames=("format",),
            registry=self.registry,
        )
        self.bytes_written_total = Counter(
            "export_bytes_written_total",
            "Total bytes streamed per export run",
            labelnames=("format",),
            registry=self.registry,
        )
        self.errors_total = Counter(
            "export_errors_total",
            "Export errors",
            labelnames=("type", "format"),
            registry=self.registry,
        )
        self.retry_total = Counter(
            "export_retry_total",
            "Retry attempts per export phase",
            labelnames=("phase", "outcome"),
            registry=self.registry,
        )
        self.retry_exhaustion_total = Counter(
            "export_exhaustion_total",
            "Times a phase exhausted retries",
            labelnames=("phase",),
            registry=self.registry,
        )
        self.retry_attempts_total = Counter(
            "export_retry_attempts_total",
            "Retry attempts for export runner",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.retries_exhausted_total = Counter(
            "export_retries_exhausted_total",
            "Retry exhaustion counts",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.rate_limit_total = Counter(
            "export_rate_limit_total",
            "Rate limit decisions for export API",
            labelnames=("outcome", "reason"),
            registry=self.registry,
        )
        self.sort_spill_chunks_total = Counter(
            "sort_spill_chunks_total",
            "Number of spilled external sort chunks",
            labelnames=("format",),
            registry=self.registry,
        )
        self.sort_spill_bytes_total = Counter(
            "sort_spill_bytes_total",
            "Bytes written during external sort spills",
            labelnames=("format",),
            registry=self.registry,
        )
        self.sort_merge_passes_total = Counter(
            "sort_merge_passes_total",
            "Number of external sort merge passes",
            labelnames=("format",),
            registry=self.registry,
        )
        self.sort_rows_total = Counter(
            "sort_rows_total",
            "Rows processed by external sorter",
            labelnames=("format",),
            registry=self.registry,
        )

    def observe_rows(self, rows: int, format_label: str) -> None:
        self.rows_total.labels(format=format_label).inc(rows)

    def observe_file_bytes(self, size: int, format_label: str) -> None:
        self.file_bytes_total.labels(format=format_label).inc(size)
        self.bytes_written_total.labels(format=format_label).inc(size)

    def inc_job(self, status: str, format_label: str) -> None:
        self.jobs_total.labels(status=status, format=format_label).inc()

    def observe_duration(self, phase: str, seconds: float, format_label: str) -> None:
        self.duration_seconds.labels(phase=phase, format=format_label).observe(seconds)

    def inc_error(self, error_type: str, format_label: str) -> None:
        self.errors_total.labels(type=error_type, format=format_label).inc()

    def inc_rate_limit(self, *, outcome: str, reason: str) -> None:
        self.rate_limit_total.labels(outcome=outcome, reason=reason).inc()

    def observe_retry(self, *, phase: str, outcome: str) -> None:
        self.retry_total.labels(phase=phase, outcome=outcome).inc()

    def observe_retry_exhaustion(self, *, phase: str) -> None:
        self.retry_exhaustion_total.labels(phase=phase).inc()

    def observe_sort_spill(self, *, format_label: str, bytes_written: int) -> None:
        self.sort_spill_chunks_total.labels(format=format_label).inc()
        self.sort_spill_bytes_total.labels(format=format_label).inc(bytes_written)

    def observe_sort_merge(self, *, format_label: str) -> None:
        self.sort_merge_passes_total.labels(format=format_label).inc()

    def observe_sort_rows(self, *, format_label: str, rows: int) -> None:
        self.sort_rows_total.labels(format=format_label).inc(rows)

    def record_retry_attempt(self, *, reason: str) -> None:
        self.retry_attempts_total.labels(reason=reason).inc()

    def record_retry_exhausted(self, *, reason: str) -> None:
        self.retries_exhausted_total.labels(reason=reason).inc()


def reset_registry(registry: CollectorRegistry) -> None:
    """Completely clear a CollectorRegistry between tests."""

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

