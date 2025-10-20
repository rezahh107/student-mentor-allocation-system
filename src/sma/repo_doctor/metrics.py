from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from .io_utils import atomic_write


@dataclass(slots=True)
class DoctorMetrics:
    path: pathlib.Path
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)
    retry_counter: Counter | None = field(init=False, default=None)
    exhausted_counter: Counter | None = field(init=False, default=None)
    duration_histogram: Histogram | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.retry_counter = Counter(
            "repo_doctor_retries_total",
            "Number of retry attempts performed by Repo Doctor",
            ("operation",),
            registry=self.registry,
        )
        self.exhausted_counter = Counter(
            "repo_doctor_exhausted_total",
            "Number of exhausted retry loops",
            ("operation",),
            registry=self.registry,
        )
        self.duration_histogram = Histogram(
            "repo_doctor_operation_duration_seconds",
            "Duration of repo doctor operations",
            ("operation",),
            registry=self.registry,
        )

    # ------------------------------------------------------------------
    def record_retry(self, operation: str) -> None:
        self.retry_counter.labels(operation=operation).inc()

    def record_exhausted(self, operation: str) -> None:
        self.exhausted_counter.labels(operation=operation).inc()

    def observe_duration(self, operation: str, seconds: float) -> None:
        self.duration_histogram.labels(operation=operation).observe(seconds)

    def flush(self) -> None:
        content = generate_latest(self.registry).decode("utf-8")
        atomic_write(self.path, content, newline="\n")


__all__ = ["DoctorMetrics"]
