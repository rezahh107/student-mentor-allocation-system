"""Minimal in-repo Prometheus client subset for tests."""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, Tuple


class CollectorRegistry:
    def __init__(self) -> None:
        self._metrics: Dict[str, "_Metric"] = {}

    def register(self, metric: "_Metric") -> None:
        self._metrics[metric.name] = metric

    def collect(self):  # pragma: no cover - compatibility
        return list(self._metrics.values())


REGISTRY = CollectorRegistry()


@dataclass
class _Metric:
    name: str
    documentation: str
    labelnames: Tuple[str, ...]
    samples: Dict[Tuple[str, ...], float]

    def labels(self, **labels: str) -> "_SampleProxy":
        key = tuple(labels.get(label, "") for label in self.labelnames)
        if key not in self.samples:
            self.samples[key] = 0.0
        return _SampleProxy(self.samples, key)


class _SampleProxy:
    def __init__(self, samples: Dict[Tuple[str, ...], float], key: Tuple[str, ...]) -> None:
        self.samples = samples
        self.key = key

    def inc(self, amount: float = 1.0) -> None:
        self.samples[self.key] = self.samples.get(self.key, 0.0) + amount

    def observe(self, value: float) -> None:
        self.inc(value)


class Counter(_Metric):
    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: Tuple[str, ...],
        registry: CollectorRegistry | None = None,
    ) -> None:
        super().__init__(name, documentation, labelnames, {})
        (registry or REGISTRY).register(self)


class Histogram(_Metric):
    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: Tuple[str, ...],
        registry: CollectorRegistry | None = None,
    ) -> None:
        super().__init__(name, documentation, labelnames, {})
        (registry or REGISTRY).register(self)


def generate_latest(registry: CollectorRegistry) -> bytes:
    buffer = io.StringIO()
    for metric in registry._metrics.values():
        for labels, value in metric.samples.items():
            label_str = ",".join(f"{name}='{val}'" for name, val in zip(metric.labelnames, labels))
            buffer.write(f"{metric.name}{{{label_str}}} {value}\n")
    return buffer.getvalue().encode("utf-8")


__all__ = ["CollectorRegistry", "Counter", "Histogram", "generate_latest"]
