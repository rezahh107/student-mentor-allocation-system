"""Prometheus metrics facade for readiness tooling."""

from __future__ import annotations

from typing import Optional

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    CollectorRegistry = None  # type: ignore
    Counter = None  # type: ignore
    Histogram = None  # type: ignore


class ReadinessMetrics:
    """Wraps Prometheus instrumentation with graceful degradation."""

    def __init__(self) -> None:
        self.registry: Optional["CollectorRegistry"] = None
        self._attempts: Optional["Counter"] = None
        self._retries: Optional["Counter"] = None
        self._exit_codes: Optional["Counter"] = None
        self._duration: Optional["Histogram"] = None
        self._setup()

    def _setup(self) -> None:
        if CollectorRegistry is None or Counter is None or Histogram is None:  # pragma: no cover
            self.registry = None
            self._attempts = None
            self._retries = None
            self._exit_codes = None
            self._duration = None
            return

        self.registry = CollectorRegistry()
        self._attempts = Counter(
            "readiness_attempts_total",
            "Total readiness evaluations run",
            registry=self.registry,
        )
        self._retries = Counter(
            "readiness_retries_total",
            "Retry loops triggered during readiness evaluation",
            ("operation",),
            registry=self.registry,
        )
        self._exit_codes = Counter(
            "readiness_exit_code_total",
            "Exit codes emitted by readiness CLI",
            ("code",),
            registry=self.registry,
        )
        self._duration = Histogram(
            "readiness_duration_seconds",
            "Synthetic readiness duration samples",
            registry=self.registry,
            buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0),
        )

    def record_attempt(self) -> None:
        if self._attempts is not None:
            self._attempts.inc()

    def record_retry(self, operation: str) -> None:
        if self._retries is not None:
            self._retries.labels(operation=operation).inc()

    def record_exit_code(self, code: int) -> None:
        if self._exit_codes is not None:
            self._exit_codes.labels(code=str(code)).inc()

    def record_duration(self, seconds: float) -> None:
        if self._duration is not None:
            self._duration.observe(seconds)

    def snapshot_retry_total(self) -> int:
        if self._retries is None:
            return 0
        samples = self._retries.collect()
        total = 0
        for metric in samples:
            for sample in metric.samples:
                total += int(sample.value)
        return total


__all__ = ["ReadinessMetrics"]

