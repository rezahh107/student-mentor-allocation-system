from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.job_runner import DeterministicRedis
from phase6_import_to_sabt.sanitization import deterministic_jitter
from phase6_import_to_sabt.xlsx.job_store import RedisExportJobStore
from phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics


class SequenceTimer:
    """Deterministic monotonic timer backed by a predefined sequence."""

    def __init__(self, values: Iterator[float]) -> None:
        self._values = iter(values)
        self._last = 0.0

    def __call__(self) -> float:
        try:
            self._last = next(self._values)
        except StopIteration:
            self._last += 0.001
        return self._last


class FlakyRedis:
    """Wrapper that injects transient Redis failures deterministically."""

    def __init__(self, *, fail_hset: int, fail_hgetall: int) -> None:
        self._inner = DeterministicRedis()
        self._fail_hset = fail_hset
        self._fail_hgetall = fail_hgetall

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        if self._fail_hset > 0:
            self._fail_hset -= 1
            raise ConnectionError("transient-hset")
        self._inner.hset(key, mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        if self._fail_hgetall > 0:
            self._fail_hgetall -= 1
            raise ConnectionError("transient-hgetall")
        return self._inner.hgetall(key)

    def expire(self, key: str, ttl: int) -> None:
        self._inner.expire(key, ttl)

    def flushdb(self) -> None:
        self._inner.flushdb()


def _collect_counter_samples(counter) -> dict[tuple[str, str], float]:
    samples: dict[tuple[str, str], float] = {}
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                operation = sample.labels.get("operation", "")
                format_label = sample.labels.get("format", "")
                samples[(operation, format_label)] = sample.value
    return samples


def _collect_hist_summaries(histogram) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    sums: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], float] = {}
    for metric in histogram.collect():
        for sample in metric.samples:
            operation = sample.labels.get("operation", "")
            format_label = sample.labels.get("format", "")
            key = (operation, format_label)
            if sample.name.endswith("_sum"):
                sums[key] = sample.value
            elif sample.name.endswith("_count"):
                counts[key] = sample.value
    return sums, counts


def test_redis_transient_failures_emit_retries_and_histograms() -> None:
    namespace = f"redis-retry:{uuid.uuid4().hex}"
    redis = FlakyRedis(fail_hset=1, fail_hgetall=1)
    registry = CollectorRegistry()
    metrics = build_import_export_metrics(registry=registry)
    metrics.reset()
    timer = SequenceTimer(iter([0.0, 0.003, 0.01, 0.013, 0.02, 0.024, 0.03, 0.033]))
    backoff_delays: list[float] = []

    store = RedisExportJobStore(
        redis=redis,
        namespace=namespace,
        now=lambda: "2024-01-01T00:00:00+03:30",
        metrics=metrics,
        sleeper=lambda seconds: backoff_delays.append(seconds),
        timer=timer,
    )

    payload = store.begin("job-redis", file_format="csv", filters={"center": 1})
    assert payload["status"] == "PENDING", {
        "context": "begin-payload",
        "payload": payload,
        "namespace": namespace,
    }

    loaded = store.load("job-redis")
    assert loaded is not None, {
        "context": "load-result",
        "redis_state": redis._inner._hash,  # type: ignore[attr-defined]
        "namespace": namespace,
    }

    attempt_samples = _collect_counter_samples(metrics.retry_total)
    exhaustion_samples = _collect_counter_samples(metrics.retry_exhausted_total)
    backoff_sums, backoff_counts = _collect_hist_summaries(metrics.retry_backoff_seconds)
    duration_sums, duration_counts = _collect_hist_summaries(metrics.retry_duration_seconds)

    redis.flushdb()
    metrics.reset()

    expected_begin_backoff = deterministic_jitter(store.base_delay, 1, "redis_begin")
    expected_read_backoff = deterministic_jitter(store.base_delay, 1, "redis_read")

    assert backoff_delays == pytest.approx([expected_begin_backoff, expected_read_backoff]), {
        "context": "backoff-delays",
        "captured": backoff_delays,
        "expected": [expected_begin_backoff, expected_read_backoff],
    }

    assert attempt_samples.get(("redis_begin", "n/a"), 0.0) == pytest.approx(1.0), {
        "context": "retry-attempts",
        "samples": attempt_samples,
    }
    assert attempt_samples.get(("redis_read", "n/a"), 0.0) == pytest.approx(1.0), {
        "context": "retry-attempts",
        "samples": attempt_samples,
    }
    assert exhaustion_samples.get(("redis_begin", "n/a"), 0.0) == 0.0, {
        "context": "exhaustion",
        "samples": exhaustion_samples,
    }
    assert exhaustion_samples.get(("redis_read", "n/a"), 0.0) == 0.0, {
        "context": "exhaustion",
        "samples": exhaustion_samples,
    }

    assert backoff_counts.get(("redis_begin", "n/a"), 0.0) == pytest.approx(1.0), {
        "context": "backoff-begin",
        "counts": backoff_counts,
    }
    assert backoff_counts.get(("redis_read", "n/a"), 0.0) == pytest.approx(1.0), {
        "context": "backoff-read",
        "counts": backoff_counts,
    }
    assert backoff_sums.get(("redis_begin", "n/a"), 0.0) == pytest.approx(expected_begin_backoff), {
        "context": "backoff-sum-begin",
        "sums": backoff_sums,
    }
    assert backoff_sums.get(("redis_read", "n/a"), 0.0) == pytest.approx(expected_read_backoff), {
        "context": "backoff-sum-read",
        "sums": backoff_sums,
    }

    assert duration_counts.get(("redis_begin", "n/a"), 0.0) == pytest.approx(2.0), {
        "context": "duration-count-begin",
        "counts": duration_counts,
    }
    assert duration_counts.get(("redis_read", "n/a"), 0.0) == pytest.approx(2.0), {
        "context": "duration-count-read",
        "counts": duration_counts,
    }
    assert duration_sums.get(("redis_begin", "n/a"), 0.0) == pytest.approx(0.006, abs=1e-6), {
        "context": "duration-sum-begin",
        "sums": duration_sums,
    }
    assert duration_sums.get(("redis_read", "n/a"), 0.0) == pytest.approx(0.007, abs=1e-6), {
        "context": "duration-sum-read",
        "sums": duration_sums,
    }
