from __future__ import annotations

import itertools

import pytest

from tooling.metrics import (
    get_retry_counter,
    get_retry_exhaustion_counter,
    get_retry_histogram,
)
from tooling.retry import RetryPolicy, retry


class FakeSleeper:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def test_exhaustion_and_histograms(metrics_registry):
    attempts = itertools.count()

    def func() -> int:
        current = next(attempts)
        if current < 2:
            raise RuntimeError("boom")
        return 42

    def should_retry(exc: BaseException) -> bool:
        return isinstance(exc, RuntimeError)

    sleeper = FakeSleeper()
    policy = RetryPolicy(attempts=3, base_delay=0.1, max_delay=1.0)
    result = retry(
        func,
        should_retry,
        policy,
        correlation_id="rid-1",
        operation="op",
        clock=sleeper,
        counter=get_retry_counter(),
        histogram=get_retry_histogram(),
        exhaustion_counter=get_retry_exhaustion_counter(),
    )
    assert result == 42
    assert len(sleeper.sleeps) == 2
    assert all(delay > 0.1 for delay in sleeper.sleeps)

    retry_count = metrics_registry.get_sample_value(
        "retries_total", {"operation": "op", "result": "retry"}
    )
    success_count = metrics_registry.get_sample_value(
        "retries_total", {"operation": "op", "result": "success"}
    )
    assert retry_count == 2
    assert success_count == 1
    exhaustion_total = metrics_registry.get_sample_value(
        "retry_exhaustions_total", {"operation": "op"}
    )
    assert exhaustion_total in (None, 0)


def test_retry_exhaustion_records_metrics(metrics_registry):
    def func() -> int:
        raise RuntimeError("boom")

    def should_retry(exc: BaseException) -> bool:
        return isinstance(exc, RuntimeError)

    sleeper = FakeSleeper()
    policy = RetryPolicy(attempts=2, base_delay=0.1, max_delay=0.2)
    with pytest.raises(RuntimeError):
        retry(
            func,
            should_retry,
            policy,
            correlation_id="rid-2",
            operation="op2",
            clock=sleeper,
            counter=get_retry_counter(),
            histogram=get_retry_histogram(),
            exhaustion_counter=get_retry_exhaustion_counter(),
        )

    exhausted = metrics_registry.get_sample_value(
        "retries_total", {"operation": "op2", "result": "exhausted"}
    )
    exhaustion_total = metrics_registry.get_sample_value(
        "retry_exhaustions_total", {"operation": "op2"}
    )
    assert exhausted == 1
    assert exhaustion_total == 1


def test_retry_fatal_records_metric(metrics_registry):
    def func() -> int:
        raise ValueError("fatal")

    def should_retry(exc: BaseException) -> bool:
        return False

    sleeper = FakeSleeper()
    policy = RetryPolicy(attempts=2, base_delay=0.1, max_delay=0.2)
    with pytest.raises(ValueError):
        retry(
            func,
            should_retry,
            policy,
            correlation_id="rid-3",
            operation="op3",
            clock=sleeper,
            counter=get_retry_counter(),
            histogram=get_retry_histogram(),
            exhaustion_counter=get_retry_exhaustion_counter(),
        )

    fatal = metrics_registry.get_sample_value(
        "retries_total", {"operation": "op3", "result": "fatal"}
    )
    assert fatal == 1
