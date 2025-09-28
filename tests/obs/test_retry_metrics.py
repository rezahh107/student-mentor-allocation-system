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
        "randomizer": lambda: 0.0,
        "monotonic": clock.tick,
    }


def test_retry_and_exhaustion_metrics(deterministic_components: dict[str, Callable]) -> None:
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
        config=security_tools.RetryConfig(max_attempts=3, base_delay=0, jitter_ratio=0),
        registry=registry,
        **deterministic_components,
    )
    assert result == "ok"
    attempts_value = registry.get_sample_value(
        "security_tool_retry_attempts_total", labels={"tool": "weak_hash_scan"}
    )
    assert attempts_value == 3.0
    exhausted = registry.get_sample_value(
        "security_tool_retry_exhausted_total", labels={"tool": "weak_hash_scan"}
    )
    assert exhausted in {None, 0.0}

    def _always_fail() -> None:
        raise RuntimeError("permanent failure")

    with pytest.raises(RuntimeError):
        security_tools.run_with_retry(
            _always_fail,
            tool_name="weak_hash_scan",
            config=security_tools.RetryConfig(max_attempts=2, base_delay=0, jitter_ratio=0),
            registry=registry,
            **deterministic_components,
        )

    exhausted_after = registry.get_sample_value(
        "security_tool_retry_exhausted_total", labels={"tool": "weak_hash_scan"}
    )
    assert exhausted_after == 1.0
