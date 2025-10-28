"""Retry observability helpers with deterministic jitter hooks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

from prometheus_client import CollectorRegistry, Counter, Histogram

T = TypeVar("T")

_BACKOFF_BUCKETS: tuple[float, ...] = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


@dataclass(slots=True)
class RetryMetrics:
    """Aggregated retry counters honoring AGENTS.md::Observability & No PII."""

    namespace: str
    registry: CollectorRegistry
    attempts_total: Counter
    exhaustion_total: Counter
    backoff_seconds: Histogram

    def record_attempts(self, *, operation: str, outcome: str, attempts: int) -> None:
        self.attempts_total.labels(operation=operation, namespace=self.namespace, outcome=outcome).inc(attempts)

    def record_exhaustion(self, *, operation: str) -> None:
        self.exhaustion_total.labels(operation=operation, namespace=self.namespace).inc()

    def observe_backoff(self, *, operation: str, delays: Iterable[float]) -> None:
        for delay in delays:
            self.backoff_seconds.labels(operation=operation, namespace=self.namespace).observe(delay)


_INVALID_METRIC_CHARS = re.compile(r"[^a-zA-Z0-9_]")


def _metric_prefix(namespace: str) -> str:
    sanitized = _INVALID_METRIC_CHARS.sub("_", namespace)
    sanitized = re.sub(r"__+", "_", sanitized).strip("_")
    return sanitized or "sma"


def build_retry_metrics(namespace: str, registry: CollectorRegistry | None = None) -> RetryMetrics:
    reg = registry or CollectorRegistry()
    prefix = _metric_prefix(namespace)
    attempts_total = Counter(
        f"{prefix}_retry_attempts_total",
        "Retry attempts recorded by operation and outcome.",
        registry=reg,
        labelnames=("operation", "namespace", "outcome"),
    )
    exhaustion_total = Counter(
        f"{prefix}_retry_exhaustion_total",
        "Retry exhaustion occurrences by operation.",
        registry=reg,
        labelnames=("operation", "namespace"),
    )
    backoff_seconds = Histogram(
        f"{prefix}_retry_backoff_seconds",
        "Retry backoff schedule seconds by operation.",
        registry=reg,
        labelnames=("operation", "namespace"),
        buckets=_BACKOFF_BUCKETS,
    )
    return RetryMetrics(
        namespace=namespace,
        registry=reg,
        attempts_total=attempts_total,
        exhaustion_total=exhaustion_total,
        backoff_seconds=backoff_seconds,
    )


def execute_with_retry(
    operation: Callable[[], T],
    *,
    policy: Callable[[int], float],
    max_attempts: int,
    metrics: RetryMetrics,
    clock_tick: Callable[[float], None],
    operation_name: str,
) -> T:
    attempts = 0
    delays: list[float] = []
    last_error: Exception | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            result = operation()
            metrics.observe_backoff(operation=operation_name, delays=delays)
            metrics.record_attempts(operation=operation_name, outcome="success", attempts=attempts)
            return result
        except Exception as exc:  # pragma: no cover - raised in tests
            last_error = exc
            if attempts >= max_attempts:
                break
            delay = policy(attempts)
            delays.append(delay)
            clock_tick(delay)
    metrics.observe_backoff(operation=operation_name, delays=delays)
    metrics.record_attempts(operation=operation_name, outcome="error", attempts=attempts)
    metrics.record_exhaustion(operation=operation_name)
    assert last_error is not None, "retry_exhaustion_missing_error"
    raise last_error


__all__ = ["RetryMetrics", "build_retry_metrics", "execute_with_retry"]
