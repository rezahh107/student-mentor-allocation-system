"""Observability tests for security tool retry metrics."""
from __future__ import annotations

from collections.abc import Callable

import pytest
from prometheus_client import CollectorRegistry

from scripts import security_tools


class Clock:
    def __init__(self) -> None:
        self._current = 0.0

    def tick(self) -> float:
        self._current += 0.01
        return self._current


@pytest.fixture
def deterministic_components() -> dict[str, Callable]:
    clock = Clock()
    return {
        "sleeper": lambda _: None,
        "monotonic": clock.tick,
    }


def _sample(registry: CollectorRegistry, name: str, labels: dict[str, str]) -> float | None:
    return registry.get_sample_value(name, labels=labels)


def test_retry_histograms_and_exhaustion(deterministic_components: dict[str, Callable]) -> None:
    registry = CollectorRegistry()
    attempts: list[int] = []

    def _flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient failure")
        return "ok"

    result = security_tools.run_with_retry(
        _flaky,
        tool_name="weak_hash_scan",
        config=security_tools.RetryConfig(max_attempts=3, base_delay=0.05, jitter_ratio=0.3),
        registry=registry,
        sleeper=deterministic_components["sleeper"],
        randomizer=None,
        monotonic=deterministic_components["monotonic"],
    )
    assert result == "ok"

    attempts_value = _sample(
        registry,
        "security_tool_retry_attempts_total",
        labels={"tool": "weak_hash_scan"},
    )
    assert attempts_value == 3.0

    exhausted = _sample(
        registry,
        "security_tool_retry_exhausted_total",
        labels={"tool": "weak_hash_scan"},
    )
    assert exhausted in {None, 0.0}

    latency_sum = _sample(
        registry,
        "security_tool_retry_latency_seconds_sum",
        labels={"tool": "weak_hash_scan"},
    )
    assert latency_sum == pytest.approx(0.03, rel=1e-6)

    sleep_count = _sample(
        registry,
        "security_tool_retry_sleep_seconds_count",
        labels={"tool": "weak_hash_scan"},
    )
    assert sleep_count == 2.0

    sleep_sum = _sample(
        registry,
        "security_tool_retry_sleep_seconds_sum",
        labels={"tool": "weak_hash_scan"},
    )
    assert sleep_sum is not None and sleep_sum > 0.05

    def _always_fail() -> None:
        raise RuntimeError("permanent failure")

    with pytest.raises(RuntimeError):
        security_tools.run_with_retry(
            _always_fail,
            tool_name="weak_hash_scan",
            config=security_tools.RetryConfig(max_attempts=2, base_delay=0.05, jitter_ratio=0.3),
            registry=registry,
            sleeper=deterministic_components["sleeper"],
            randomizer=None,
            monotonic=deterministic_components["monotonic"],
        )

    exhausted_after = _sample(
        registry,
        "security_tool_retry_exhausted_total",
        labels={"tool": "weak_hash_scan"},
    )
    assert exhausted_after == 1.0

    latency_sum_after = _sample(
        registry,
        "security_tool_retry_latency_seconds_sum",
        labels={"tool": "weak_hash_scan"},
    )
    assert latency_sum_after == pytest.approx(0.05, rel=1e-6)

    sleep_count_after = _sample(
        registry,
        "security_tool_retry_sleep_seconds_count",
        labels={"tool": "weak_hash_scan"},
    )
    assert sleep_count_after == 3.0

