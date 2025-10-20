"""Prometheus metrics for the counter runtime."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, REGISTRY


class CounterRuntimeMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._alloc_total = self._get_or_create_counter(
            "counter_alloc_total",
            "Total counter allocation outcomes",
            ("status",),
        )
        self._retry_total = self._get_or_create_counter(
            "counter_retry_total",
            "Total retries performed by the counter runtime",
            ("operation",),
        )
        self._exhausted_total = self._get_or_create_counter(
            "counter_exhausted_total",
            "Counter sequence exhaustion per year and gender",
            ("year_code", "gender"),
        )

    def _get_or_create_counter(
        self,
        name: str,
        documentation: str,
        labelnames: tuple[str, ...],
    ) -> Counter:
        try:
            return Counter(name, documentation, labelnames, registry=self._registry)
        except ValueError:
            collector = self._registry._names_to_collectors.get(name)  # type: ignore[attr-defined]
            if collector is None:
                raise
            return collector  # type: ignore[return-value]

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def record_alloc(self, status: str) -> None:
        self._alloc_total.labels(status=status).inc()

    def record_retry(self, operation: str, attempts: int = 1) -> None:
        self._retry_total.labels(operation=operation).inc(max(1, attempts))

    def record_exhausted(self, year_code: str, gender: int) -> None:
        self._exhausted_total.labels(year_code=year_code, gender=str(gender)).inc()


__all__ = ["CounterRuntimeMetrics"]
