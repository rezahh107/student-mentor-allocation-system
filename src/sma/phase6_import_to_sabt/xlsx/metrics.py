from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram


@dataclass(slots=True)
class ImportExportMetrics:
    registry: CollectorRegistry
    export_jobs_total: Counter
    export_duration_seconds: Histogram
    export_rows_total: Counter
    export_file_bytes_total: Counter
    upload_jobs_total: Counter
    upload_rows_total: Counter
    retry_total: Counter
    retry_exhausted_total: Counter
    retry_backoff_seconds: Histogram
    retry_duration_seconds: Histogram
    download_signed_total: Counter

    def reset(self) -> None:
        if hasattr(self.registry, "_names_to_collectors"):
            self.registry._names_to_collectors.clear()  # type: ignore[attr-defined]
        if hasattr(self.registry, "_collector_to_names"):
            self.registry._collector_to_names.clear()  # type: ignore[attr-defined]


def build_import_export_metrics(registry: CollectorRegistry | None = None) -> ImportExportMetrics:
    reg = registry or CollectorRegistry()
    export_jobs_total = Counter(
        "export_jobs_total",
        "Total export jobs by status and format",
        labelnames=("status", "format"),
        registry=reg,
    )
    export_duration_seconds = Histogram(
        "export_duration_seconds",
        "Export duration seconds by phase",
        labelnames=("phase", "format"),
        registry=reg,
        buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1.0),
    )
    export_rows_total = Counter(
        "export_rows_total",
        "Total exported rows by format",
        labelnames=("format",),
        registry=reg,
    )
    export_file_bytes_total = Counter(
        "export_file_bytes_total",
        "Total bytes written per format",
        labelnames=("format",),
        registry=reg,
    )
    upload_jobs_total = Counter(
        "upload_jobs_total",
        "Upload jobs by status and format",
        labelnames=("status", "format"),
        registry=reg,
    )
    upload_rows_total = Counter(
        "upload_rows_total",
        "Uploaded rows per format",
        labelnames=("format",),
        registry=reg,
    )
    retry_total = Counter(
        "io_retry_total",
        "Retry attempts by operation and format",
        labelnames=("operation", "format"),
        registry=reg,
    )
    retry_exhausted_total = Counter(
        "io_retry_exhausted_total",
        "Retry exhaustions by operation and format",
        labelnames=("operation", "format"),
        registry=reg,
    )
    retry_backoff_seconds = Histogram(
        "io_retry_backoff_seconds",
        "Observed retry backoff seconds by operation and format",
        labelnames=("operation", "format"),
        registry=reg,
        buckets=(0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5),
    )
    retry_duration_seconds = Histogram(
        "io_retry_duration_seconds",
        "Operation attempt durations during retry orchestration",
        labelnames=("operation", "format"),
        registry=reg,
        buckets=(0.0005, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1),
    )
    download_signed_total = Counter(
        "download_signed_total",
        "Signed download URL activity",
        labelnames=("outcome",),
        registry=reg,
    )
    return ImportExportMetrics(
        registry=reg,
        export_jobs_total=export_jobs_total,
        export_duration_seconds=export_duration_seconds,
        export_rows_total=export_rows_total,
        export_file_bytes_total=export_file_bytes_total,
        upload_jobs_total=upload_jobs_total,
        upload_rows_total=upload_rows_total,
        retry_total=retry_total,
        retry_exhausted_total=retry_exhausted_total,
        retry_backoff_seconds=retry_backoff_seconds,
        retry_duration_seconds=retry_duration_seconds,
        download_signed_total=download_signed_total,
    )
