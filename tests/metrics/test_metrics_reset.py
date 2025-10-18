from __future__ import annotations

import importlib
import os
import sys
import types
from contextlib import contextmanager

import pytest

MODULE_NAME = "repo_auditor_lite.metrics"
_SENTINEL = object()


def _set_backend(value):
    if value is _SENTINEL:
        return
    if value is None:
        os.environ.pop("AUDITOR_METRICS_BACKEND", None)
    else:
        os.environ["AUDITOR_METRICS_BACKEND"] = value


def _value(counter) -> float:
    collected = counter.collect()
    if not collected:
        return 0.0
    samples = collected[0].samples
    return samples[0].value if samples else 0.0


def _restore_metrics(original_prom, original_backend) -> None:
    sys.modules.pop(MODULE_NAME, None)
    if original_prom is _SENTINEL:
        sys.modules.pop("prometheus_client", None)
    else:
        sys.modules["prometheus_client"] = original_prom
    if original_backend is _SENTINEL:
        os.environ.pop("AUDITOR_METRICS_BACKEND", None)
    else:
        os.environ["AUDITOR_METRICS_BACKEND"] = original_backend
    importlib.import_module(MODULE_NAME)


@contextmanager
def override_prometheus(module: types.ModuleType | None, backend=_SENTINEL):
    original_prom = sys.modules.get("prometheus_client", _SENTINEL)
    original_backend = os.environ.get("AUDITOR_METRICS_BACKEND", _SENTINEL)
    sys.modules.pop(MODULE_NAME, None)
    if module is None:
        sys.modules["prometheus_client"] = None  # force ModuleNotFoundError
    else:
        sys.modules["prometheus_client"] = module
    _set_backend(backend)
    try:
        yield importlib.import_module(MODULE_NAME)
    finally:
        _restore_metrics(original_prom, original_backend)


def _build_fake_prometheus() -> types.ModuleType:
    fake_module = types.ModuleType("prometheus_client")

    class FakeCollectorRegistry:
        def __init__(self) -> None:
            self.metrics = []

        def register(self, metric) -> None:
            self.metrics.append(metric)

    class FakeCounter:
        def __init__(self, name: str, documentation: str, labelnames, registry: FakeCollectorRegistry) -> None:
            self._labelnames = tuple(labelnames)
            self._values: dict[tuple[str, ...], float] = {}
            self._current_key: tuple[str, ...] | None = None
            registry.register(self)

        def labels(self, **labels: str) -> "FakeCounter":
            key = tuple(labels[name] for name in self._labelnames)
            if key not in self._values:
                self._values[key] = 0.0
            self._current_key = key
            return self

        def inc(self, amount: float = 1.0) -> None:
            if self._current_key is None:
                raise RuntimeError("labels() must be called before inc()")
            self._values[self._current_key] += float(amount)

        def collect(self):
            metric = types.SimpleNamespace(samples=[])
            for value in self._values.values():
                metric.samples.append(types.SimpleNamespace(value=value))
            return [metric]

    class FakeGauge(FakeCounter):
        def set(self, value: float) -> None:
            if self._current_key is None:
                raise RuntimeError("labels() must be called before set()")
            self._values[self._current_key] = float(value)

        def dec(self, amount: float = 1.0) -> None:
            if self._current_key is None:
                raise RuntimeError("labels() must be called before dec()")
            self._values[self._current_key] -= float(amount)

    FakeCollectorRegistry.__module__ = fake_module.__name__
    FakeCounter.__module__ = fake_module.__name__
    FakeGauge.__module__ = fake_module.__name__

    fake_module.CollectorRegistry = FakeCollectorRegistry  # type: ignore[attr-defined]
    fake_module.Counter = FakeCounter  # type: ignore[attr-defined]
    fake_module.Gauge = FakeGauge  # type: ignore[attr-defined]
    return fake_module


def test_registry_resets_between_tests() -> None:
    metrics = importlib.import_module(MODULE_NAME)
    metrics.inc_retry("write")
    assert _value(metrics.counters()["retry_total"]) == 1.0
    metrics.reset_registry()
    assert _value(metrics.counters()["retry_total"]) == 0.0


def test_metrics_noop_fallback() -> None:
    with override_prometheus(None, backend=None) as metrics:
        metrics.reset_registry()
        metrics.inc_retry("noop")
        counter = metrics.counters()["retry_total"]
        assert counter.__class__.__module__.endswith("metrics_noop")
        assert _value(counter) == 1.0


def test_metrics_prefers_prometheus_stub() -> None:
    fake_module = _build_fake_prometheus()
    with override_prometheus(fake_module, backend=None) as metrics:
        metrics.reset_registry()
        metrics.inc_retry("real")
        counter = metrics.counters()["retry_total"]
        assert counter.__class__.__module__ == "prometheus_client"
        assert _value(counter) == 1.0


def test_metrics_forced_noop_backend_uses_noop_even_with_prometheus() -> None:
    fake_module = _build_fake_prometheus()
    with override_prometheus(fake_module, backend="noop") as metrics:
        assert metrics.METRICS_BACKEND == "noop"
        counter = metrics.counters()["retry_total"]
        assert counter.__class__.__module__.endswith("metrics_noop")


def test_metrics_forced_prom_backend_requires_dependency() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        with override_prometheus(None, backend="prom"):
            pass
    assert "prometheus_client" in str(excinfo.value)


def test_metrics_forced_prom_backend_uses_stub_when_available() -> None:
    fake_module = _build_fake_prometheus()
    with override_prometheus(fake_module, backend="prom") as metrics:
        assert metrics.METRICS_BACKEND == "prom"
        counter = metrics.counters()["retry_total"]
        metrics.reset_registry()
        counter.labels(operation="forced").inc()
        assert _value(counter) == 1.0
