from __future__ import annotations

import json
import math
import os
import statistics
import time
import tracemalloc
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, MutableMapping
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from sma.core.clock import FrozenClock
from sma.core.retry import RetryPolicy, build_sync_clock_sleeper, execute_with_retry
from sma._local_fakeredis import FakeStrictRedis

_TEHRAN_TZ = ZoneInfo("Asia/Tehran")

if os.getenv("SMA_PERF_FAST") is None:
    os.environ["SMA_PERF_FAST"] = "1"


def _stringify_keys(raw_keys: list[Any]) -> list[str]:
    rendered: list[str] = []
    for key in raw_keys:
        if isinstance(key, bytes):
            rendered.append(key.decode("utf-8", "ignore"))
        else:
            rendered.append(str(key))
    return sorted(rendered)


@dataclass(slots=True)
class _SampleBucket:
    durations: list[float]
    peaks: list[int]


class PerformanceMonitor:
    """Capture deterministic performance metrics with cleanup and retries."""

    def __init__(self, namespace: str, redis_client: FakeStrictRedis, metrics_path: Path) -> None:
        self.namespace = namespace
        self.redis = redis_client
        self.metrics_path = metrics_path
        self._samples: MutableMapping[str, _SampleBucket] = defaultdict(lambda: _SampleBucket([], []))
        self._clock = FrozenClock(timezone=_TEHRAN_TZ)
        self._clock.set(datetime(2024, 1, 1, tzinfo=_TEHRAN_TZ))
        self._policy = RetryPolicy(base_delay=0.05, factor=2.0, max_delay=0.5, max_attempts=3)
        self._sleeper = build_sync_clock_sleeper(self._clock)
        tracemalloc.start()
        self.redis.flushdb()

    def key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    def debug(self, label: str) -> Dict[str, Any]:
        bucket = self._samples[label]
        return {
            "label": label,
            "namespace": self.namespace,
            "samples": len(bucket.durations),
            "durations": list(bucket.durations),
            "memory_peaks": list(bucket.peaks),
            "redis_keys": _stringify_keys(self.redis.keys("*")),
            "env": {
                "PYTEST_PERF_METRICS_PATH": os.getenv("PYTEST_PERF_METRICS_PATH", ""),
                "GITHUB_ACTIONS": os.getenv("GITHUB_ACTIONS", "local"),
            },
            "clock": self._clock.now().isoformat(),
        }

    def _flush_state(self) -> None:
        self.redis.flushdb()

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        self._flush_state()
        tracemalloc.reset_peak()
        start = time.perf_counter()
        try:
            yield
        except Exception as exc:  # pragma: no cover - enrich failure context
            context = f"عملیات {label} با شکست مواجه شد؛ زمینه: {json.dumps(self.debug(label), ensure_ascii=False)}"
            add_note = getattr(exc, "add_note", None)
            if callable(add_note):
                add_note(context)
                raise
            raise AssertionError(context) from exc
        else:
            duration = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
            bucket = self._samples[label]
            bucket.durations.append(duration)
            bucket.peaks.append(int(peak))
        finally:
            self._flush_state()
            # Advance frozen clock slightly to keep retries deterministic without wall-clock.
            self._clock.tick(0.001)

    def run_with_retry(
        self,
        label: str,
        func: Callable[[], Any],
        *,
        retryable: tuple[type[Exception], ...] = (Exception,),
    ) -> Any:
        def _operation() -> Any:
            with self.measure(label):
                return func()

        correlation = f"{self.namespace}:{label}"
        return execute_with_retry(
            _operation,
            policy=self._policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=retryable,
            correlation_id=correlation,
            op=label,
        )

    def percentile(self, label: str, percentile: float) -> float:
        bucket = self._samples[label]
        data = sorted(bucket.durations)
        if not data:
            return 0.0
        rank = max(0, math.ceil((percentile / 100.0) * len(data)) - 1)
        return data[min(rank, len(data) - 1)]

    def peak_memory(self, label: str) -> int:
        bucket = self._samples[label]
        return max(bucket.peaks, default=0)

    def metrics_snapshot(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for label, bucket in self._samples.items():
            durations = bucket.durations
            peaks = bucket.peaks
            summary[label] = {
                "samples": len(durations),
                "p95_seconds": self.percentile(label, 95),
                "mean_seconds": statistics.mean(durations) if durations else 0.0,
                "max_seconds": max(durations, default=0.0),
                "peak_memory_bytes": max(peaks, default=0),
                "mean_memory_bytes": int(statistics.mean(peaks)) if peaks else 0,
            }
        return {
            "namespace": self.namespace,
            "generated_at": self._clock.now().isoformat(),
            "metrics": summary,
        }

    def persist(self) -> None:
        payload = self.metrics_snapshot()
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        try:
            self.redis.flushdb()
        finally:
            if tracemalloc.is_tracing():
                tracemalloc.stop()


@pytest.fixture(scope="session")
def performance_monitor() -> Iterator[PerformanceMonitor]:
    metrics_path = Path(os.getenv("PYTEST_PERF_METRICS_PATH", "test-results/performance-metrics.json"))
    redis_client = FakeStrictRedis()
    monitor = PerformanceMonitor(namespace=f"perf:{uuid4().hex}", redis_client=redis_client, metrics_path=metrics_path)
    previous_flag = os.environ.get("SMA_PERF_FAST")
    os.environ["SMA_PERF_FAST"] = "1"
    try:
        yield monitor
    finally:
        monitor.persist()
        monitor.close()
        if previous_flag is None:
            os.environ.pop("SMA_PERF_FAST", None)
        else:
            os.environ["SMA_PERF_FAST"] = previous_flag


@pytest.fixture(scope="function")
def benchmark(timing_control: "TimingHarness") -> Iterator[Callable[[Callable[..., Any]], Any]]:
    """Deterministic benchmark fixture aligned with timing control harness."""

    class _BenchmarkHarness:
        def __init__(self) -> None:
            self.stats = {"data": [], "mean": 0.0}

        def __call__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            start = timing_control.perf_counter()
            result = func(*args, **kwargs)
            duration = timing_control.perf_counter() - start
            self.stats["mean"] = float(duration)
            self.stats.setdefault("data", []).append(float(duration))
            return result

        def pedantic(
            self,
            func: Callable[..., Any],
            *,
            iterations: int = 1,
            rounds: int = 1,
            args: tuple[Any, ...] | None = None,
            kwargs: dict[str, Any] | None = None,
        ) -> "_BenchmarkHarness":
            samples: list[float] = []
            for _ in range(max(1, rounds)):
                for _ in range(max(1, iterations)):
                    start = timing_control.perf_counter()
                    func(*(args or ()), **(kwargs or {}))
                    samples.append(timing_control.perf_counter() - start)
            self.stats["data"] = samples
            if samples:
                self.stats["mean"] = float(sum(samples) / len(samples))
            else:
                self.stats["mean"] = 0.0
            return self

    harness = _BenchmarkHarness()
    yield harness
