"""Prometheus metrics helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from prometheus_client import CollectorRegistry, Counter, Histogram


@dataclass
class SyncMetrics:
    """Encapsulate Prometheus metrics with deterministic registry usage."""

    registry: CollectorRegistry = field(default_factory=CollectorRegistry)

    def __post_init__(self) -> None:
        self.sync_attempts_total = Counter(
            "sync_attempts_total",
            "Total sync attempts.",
            registry=self.registry,
        )
        self.sync_retries_total = Counter(
            "sync_retries_total",
            "Total sync retries.",
            registry=self.registry,
        )
        self.sync_exit_code_total = Counter(
            "sync_exit_code_total",
            "Sync exit codes.",
            labelnames=("code",),
            registry=self.registry,
        )
        self.sync_duration_seconds = Histogram(
            "sync_duration_seconds",
            "Sync duration in seconds.",
            registry=self.registry,
            buckets=(0.05, 0.1, 0.2, 0.4, 0.6, 1.0, 1.5, 2.0),
        )

    def record_attempt(self) -> None:
        """Increment attempt counter."""
        self.sync_attempts_total.inc()

    def record_retries(self, count: int) -> None:
        """Record retries."""
        if count > 0:
            self.sync_retries_total.inc(count)

    def record_exit_code(self, code: int) -> None:
        """Record exit code."""
        self.sync_exit_code_total.labels(code=str(code)).inc()

    def observe_duration(self, seconds: float) -> None:
        """Observe duration."""
        self.sync_duration_seconds.observe(seconds)
