from __future__ import annotations

"""Prometheus metrics helpers for ops dashboards."""

from prometheus_client import CollectorRegistry, Counter, Histogram


def _build_registry() -> tuple[
    CollectorRegistry,
    Counter,
    Histogram,
    Counter,
    Counter,
    Counter,
    Counter,
]:
    registry = CollectorRegistry()
    export_job_total = Counter(
        "export_jobs_total",
        "Total export jobs grouped by status.",
        labelnames=("status",),
        registry=registry,
    )
    export_duration_seconds = Histogram(
        "export_duration_seconds",
        "Export duration distribution per phase.",
        labelnames=("phase",),
        registry=registry,
    )
    export_rows_total = Counter(
        "export_rows_total",
        "Rows processed by export jobs.",
        labelnames=("type",),
        registry=registry,
    )
    export_file_bytes_total = Counter(
        "export_file_bytes_total",
        "Bytes emitted by export jobs.",
        labelnames=("kind",),
        registry=registry,
    )
    upload_errors_total = Counter(
        "upload_errors_total",
        "Upload errors by type.",
        labelnames=("type",),
        registry=registry,
    )
    ops_read_retries = Counter(
        "ops_read_retries_total",
        "Replica read retries recorded by the ops service.",
        registry=registry,
    )
    return (
        registry,
        export_job_total,
        export_duration_seconds,
        export_rows_total,
        export_file_bytes_total,
        upload_errors_total,
        ops_read_retries,
    )


REGISTRY, EXPORT_JOB_TOTAL, EXPORT_DURATION_SECONDS, EXPORT_ROWS_TOTAL, EXPORT_FILE_BYTES_TOTAL, UPLOAD_ERRORS_TOTAL, OPS_READ_RETRIES = _build_registry()


def reset_metrics_registry() -> None:
    global REGISTRY, EXPORT_JOB_TOTAL, EXPORT_DURATION_SECONDS, EXPORT_ROWS_TOTAL, EXPORT_FILE_BYTES_TOTAL, UPLOAD_ERRORS_TOTAL, OPS_READ_RETRIES
    (
        REGISTRY,
        EXPORT_JOB_TOTAL,
        EXPORT_DURATION_SECONDS,
        EXPORT_ROWS_TOTAL,
        EXPORT_FILE_BYTES_TOTAL,
        UPLOAD_ERRORS_TOTAL,
        OPS_READ_RETRIES,
    ) = _build_registry()


__all__ = [
    "REGISTRY",
    "EXPORT_JOB_TOTAL",
    "EXPORT_DURATION_SECONDS",
    "EXPORT_ROWS_TOTAL",
    "EXPORT_FILE_BYTES_TOTAL",
    "UPLOAD_ERRORS_TOTAL",
    "OPS_READ_RETRIES",
    "reset_metrics_registry",
]
