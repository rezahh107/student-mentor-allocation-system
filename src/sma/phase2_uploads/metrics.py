from __future__ import annotations

from dataclasses import dataclass, field
from prometheus_client import Counter, Histogram, CollectorRegistry


@dataclass(slots=True)
class UploadsMetrics:
    registry: CollectorRegistry
    uploads_total: Counter = field(init=False)
    upload_duration: Histogram = field(init=False)
    upload_bytes: Counter = field(init=False)
    upload_errors: Counter = field(init=False)

    def __post_init__(self) -> None:
        self.uploads_total = Counter(
            "uploads_total",
            "Total uploads processed",
            labelnames=("status", "format"),
            registry=self.registry,
        )
        self.upload_duration = Histogram(
            "upload_duration_seconds",
            "Upload duration in seconds",
            labelnames=("phase",),
            registry=self.registry,
            buckets=(0.05, 0.1, 0.2, 0.5, 1, 3, 6, 10),
        )
        self.upload_bytes = Counter(
            "upload_file_bytes_total",
            "Total bytes processed for uploads",
            registry=self.registry,
        )
        self.upload_errors = Counter(
            "upload_errors_total",
            "Total upload errors",
            labelnames=("type",),
            registry=self.registry,
        )

    def record_success(self, fmt: str, duration: float, size: int) -> None:
        self.uploads_total.labels(status="success", format=fmt).inc()
        self.upload_duration.labels(phase="persist").observe(duration)
        self.upload_bytes.inc(size)

    def record_failure(self, fmt: str, error_type: str) -> None:
        self.uploads_total.labels(status="failure", format=fmt).inc()
        self.upload_errors.labels(type=error_type).inc()
