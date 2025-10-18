"""Minimal Prometheus-compatible shims for environments without prometheus_client."""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

__all__ = ["CollectorRegistry", "Counter", "Gauge"]


class CollectorRegistry:
    """In-memory registry that keeps references to created metrics."""

    def __init__(self) -> None:
        self._metrics: list[_BaseMetric] = []

    def register(self, metric: "_BaseMetric") -> None:
        self._metrics.append(metric)

    def collect(self) -> Iterable["_MetricSnapshot"]:
        for metric in self._metrics:
            yield metric._snapshot()


class _Sample:
    __slots__ = ("value",)

    def __init__(self, value: float) -> None:
        self.value = float(value)


class _MetricSnapshot:
    __slots__ = ("samples",)

    def __init__(self, values: Iterable[float]) -> None:
        self.samples = [_Sample(value) for value in values]


class _BaseMetric:
    def __init__(self, labelnames: Tuple[str, ...], registry: CollectorRegistry) -> None:
        self._labelnames = labelnames
        self._values: Dict[Tuple[str, ...], float] = {}
        self._current_key: Tuple[str, ...] | None = None
        registry.register(self)

    def labels(self, **labels: str) -> "_BaseMetric":
        key = tuple(labels[name] for name in self._labelnames)
        if key not in self._values:
            self._values[key] = self._initial_value()
        self._current_key = key
        return self

    def _initial_value(self) -> float:
        return 0.0

    def _snapshot(self) -> _MetricSnapshot:
        return _MetricSnapshot(self._values.values())


class Counter(_BaseMetric):
    """Simplified Counter implementation compatible with prometheus_client.Counter."""

    def __init__(self, name: str, documentation: str, labelnames, registry: CollectorRegistry) -> None:
        super().__init__(tuple(labelnames), registry)
        self._name = name
        self._documentation = documentation

    def inc(self, amount: float = 1.0) -> None:
        if self._current_key is None:
            raise RuntimeError("labels() must be called before inc() in noop Counter")
        self._values[self._current_key] += float(amount)

    def collect(self):
        return [self._snapshot()]


class Gauge(_BaseMetric):
    """Simplified Gauge implementation for parity with prometheus_client.Gauge."""

    def __init__(self, name: str, documentation: str, labelnames, registry: CollectorRegistry) -> None:
        super().__init__(tuple(labelnames), registry)
        self._name = name
        self._documentation = documentation

    def set(self, value: float) -> None:
        if self._current_key is None:
            raise RuntimeError("labels() must be called before set() in noop Gauge")
        self._values[self._current_key] = float(value)

    def inc(self, amount: float = 1.0) -> None:
        if self._current_key is None:
            raise RuntimeError("labels() must be called before inc() in noop Gauge")
        self._values[self._current_key] += float(amount)

    def dec(self, amount: float = 1.0) -> None:
        if self._current_key is None:
            raise RuntimeError("labels() must be called before dec() in noop Gauge")
        self._values[self._current_key] -= float(amount)

    def collect(self):
        return [self._snapshot()]
