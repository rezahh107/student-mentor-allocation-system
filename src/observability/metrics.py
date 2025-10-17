"""Lightweight observability helpers shared across services."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import quantiles
from typing import Sequence

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

__all__ = [
    "PerformanceBudgets",
    "MetricsBundle",
    "PerformanceMonitor",
    "create_metrics",
    "reset_registry",
]


@dataclass(slots=True)
class PerformanceBudgets:
    """Declare deterministic performance budgets for latency and memory."""

    exporter_p95_seconds: float = 0.2
    signing_p95_seconds: float = 0.2
    memory_peak_mb: float = 300.0


@dataclass(slots=True)
class MetricsBundle:
    """Aggregated Prometheus instrumentation for exporter/signing flows."""

    registry: CollectorRegistry
    exporter_latency: Histogram
    signing_latency: Histogram
    memory_peak: Gauge
    retry_attempts: Counter
    retry_exhausted: Counter


def create_metrics(namespace: str) -> MetricsBundle:
    registry = CollectorRegistry()
    exporter_latency = Histogram(
        f"{namespace}_exporter_latency_seconds",
        "Exporter write latency",
        registry=registry,
        buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1.0),
    )
    signing_latency = Histogram(
        f"{namespace}_signing_latency_seconds",
        "Signing latency",
        registry=registry,
        buckets=(0.005, 0.01, 0.05, 0.1, 0.2),
    )
    memory_peak = Gauge(
        f"{namespace}_memory_peak_bytes",
        "Peak memory consumption",
        registry=registry,
    )
    retry_attempts = Counter(
        f"{namespace}_retry_attempts_total",
        "Retry attempts per operation",
        registry=registry,
        labelnames=("operation",),
    )
    retry_exhausted = Counter(
        f"{namespace}_retry_exhausted_total",
        "Retry exhaustion per operation",
        registry=registry,
        labelnames=("operation",),
    )
    return MetricsBundle(
        registry=registry,
        exporter_latency=exporter_latency,
        signing_latency=signing_latency,
        memory_peak=memory_peak,
        retry_attempts=retry_attempts,
        retry_exhausted=retry_exhausted,
    )


@dataclass
class PerformanceMonitor:
    """Track latencies and check deterministic performance budgets."""

    metrics: MetricsBundle
    budgets: PerformanceBudgets
    exporter_samples: list[float] = field(default_factory=list)
    signing_samples: list[float] = field(default_factory=list)
    memory_samples: list[int] = field(default_factory=list)

    def record_export(self, *, duration: float, memory_bytes: int) -> None:
        self.exporter_samples.append(duration)
        self.memory_samples.append(memory_bytes)
        self.metrics.exporter_latency.observe(duration)
        self.metrics.memory_peak.set(max(self.memory_samples))

    def record_signing(self, *, duration: float, memory_bytes: int) -> None:
        self.signing_samples.append(duration)
        self.memory_samples.append(memory_bytes)
        self.metrics.signing_latency.observe(duration)
        self.metrics.memory_peak.set(max(self.memory_samples))

    def record_retry(self, operation: str, attempts: int, exhausted: bool) -> None:
        if attempts:
            self.metrics.retry_attempts.labels(operation=operation).inc(attempts)
        if exhausted:
            self.metrics.retry_exhausted.labels(operation=operation).inc()

    def ensure_within_budget(self) -> dict[str, float]:
        exporter_p95 = _p95(self.exporter_samples)
        signing_p95 = _p95(self.signing_samples)
        memory_peak_mb = max((sample for sample in self.memory_samples), default=0) / (1024 * 1024)
        violations: list[str] = []
        if exporter_p95 > self.budgets.exporter_p95_seconds:
            violations.append("EXPORTER_P95")
        if signing_p95 > self.budgets.signing_p95_seconds:
            violations.append("SIGNING_P95")
        if memory_peak_mb > self.budgets.memory_peak_mb:
            violations.append("MEMORY_PEAK")
        if violations:
            raise AssertionError(
                "؛".join(
                    [
                        "«عملکرد از بودجه تعیین‌شده فراتر رفت.»",
                        f"موارد نقض: {','.join(violations)}",
                        f"صادرات p95={exporter_p95:.4f}s",
                        f"امضا p95={signing_p95:.4f}s",
                        f"بیشینه حافظه={memory_peak_mb:.2f}MB",
                    ]
                )
            )
        return {
            "exporter_p95": exporter_p95,
            "signing_p95": signing_p95,
            "memory_peak_mb": memory_peak_mb,
        }


def reset_registry(registry: CollectorRegistry) -> None:
    if hasattr(registry, "_names_to_collectors"):
        registry._names_to_collectors.clear()  # type: ignore[attr-defined]
    if hasattr(registry, "_collector_to_names"):
        registry._collector_to_names.clear()  # type: ignore[attr-defined]


def _p95(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    if len(samples) == 1:
        return float(samples[0])
    ordered = sorted(float(item) for item in samples)
    try:
        return quantiles(ordered, n=100)[94]
    except Exception:  # pragma: no cover - fallback for edge inputs
        index = int(0.95 * (len(ordered) - 1))
        return ordered[index]


