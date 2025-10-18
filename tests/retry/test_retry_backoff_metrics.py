from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import os
import pytest
from prometheus_client import CollectorRegistry

from core.clock import FrozenClock, validate_timezone
from core.retry import RetryPolicy
from phase6_import_to_sabt.app.io_utils import write_atomic
from phase6_import_to_sabt.obs.metrics import ServiceMetrics, build_metrics


@pytest.fixture
def service_metrics() -> Iterator[ServiceMetrics]:
    registry = CollectorRegistry()
    metrics = build_metrics("retry_fs", registry=registry)
    metrics.reset()
    yield metrics
    metrics.reset()


def test_fs_atomic_write_with_transient_failures_emits_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_metrics: ServiceMetrics,
) -> None:
    tz = validate_timezone("Asia/Tehran")
    clock = FrozenClock(timezone=tz)
    clock.set(datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tehran")))

    target = tmp_path / "exports" / "result.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    attempts: list[int] = []

    original_replace = os.replace

    def flaky_replace(src: str | bytes | Path, dst: str | bytes | Path) -> None:
        if not attempts:
            attempts.append(1)
            raise OSError("simulated-busy-fs")
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    payload = "سلام، این یک آزمون است.".encode("utf-8")
    policy = RetryPolicy(base_delay=0.05, factor=2.0, max_delay=0.2, max_attempts=3)
    backoff_expected = policy.backoff_for(1, correlation_id="fs-corr", op="fs.write")

    try:
        write_atomic(
            target,
            payload,
            retry_policy=policy,
            metrics=service_metrics,
            correlation_id="fs-corr",
            sleeper=lambda seconds: clock.tick(seconds),
            operation="fs.write",
            route="default",
            clock=clock,
            on_retry=lambda attempt: attempts.append(attempt + 1),
        )
    finally:
        monkeypatch.setattr(os, "replace", original_replace)

    assert target.read_bytes() == payload, {
        "context": "file-persisted",
        "attempts": attempts,
        "path": str(target),
    }

    attempt_samples = {
        (sample.labels["operation"], sample.labels["route"]): sample.value
        for metric in service_metrics.retry_attempts_total.collect()
        for sample in metric.samples
        if sample.name.endswith("_total")
    }
    assert attempt_samples.get(("fs.write", "default")) == pytest.approx(2.0), {
        "context": "retry-attempts",
        "samples": attempt_samples,
    }

    exhaustion_samples = {
        (sample.labels["operation"], sample.labels["route"]): sample.value
        for metric in service_metrics.retry_exhausted_total.collect()
        for sample in metric.samples
        if sample.name.endswith("_total")
    }
    assert exhaustion_samples.get(("fs.write", "default"), 0.0) == 0.0, {
        "context": "exhaustion-counter",
        "samples": exhaustion_samples,
    }

    histogram_samples = list(service_metrics.retry_backoff_seconds.collect()[0].samples)
    sum_sample = next(sample for sample in histogram_samples if sample.name.endswith("_sum"))
    assert sum_sample.value == pytest.approx(backoff_expected), {
        "context": "backoff-sum",
        "expected": backoff_expected,
        "samples": histogram_samples,
    }

    count_sample = next(sample for sample in histogram_samples if sample.name.endswith("_count"))
    assert count_sample.value == pytest.approx(1.0), {
        "context": "backoff-count",
        "samples": histogram_samples,
    }

