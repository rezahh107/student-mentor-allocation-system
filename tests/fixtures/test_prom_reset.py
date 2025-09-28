"""Prometheus registry hygiene for retry metrics."""
from __future__ import annotations

from collections.abc import Callable

import pytest
from prometheus_client import CollectorRegistry

from scripts import security_tools


@pytest.fixture
def deterministic_clock() -> Callable[[], float]:
    value = 100.0

    def _tick() -> float:
        nonlocal value
        value += 0.5
        return value

    return _tick


def test_prom_registry_reset(monkeypatch: pytest.MonkeyPatch, deterministic_clock) -> None:
    registry = CollectorRegistry()
    security_tools.reset_metrics(registry=registry)

    def _succeed() -> str:
        return "ok"

    result = security_tools.run_with_retry(
        _succeed,
        tool_name="demo",
        config=security_tools.RetryConfig(max_attempts=1, base_delay=0, jitter_ratio=0),
        registry=registry,
        sleeper=lambda _: None,
        randomizer=lambda: 0.0,
        monotonic=deterministic_clock,
    )
    assert result == "ok"
    attempts = registry.get_sample_value(
        "security_tool_retry_attempts_total", labels={"tool": "demo"}
    )
    assert attempts == 1.0

    security_tools.reset_metrics(registry=registry)
    result = security_tools.run_with_retry(
        _succeed,
        tool_name="demo",
        config=security_tools.RetryConfig(max_attempts=1, base_delay=0, jitter_ratio=0),
        registry=registry,
        sleeper=lambda _: None,
        randomizer=lambda: 0.0,
        monotonic=deterministic_clock,
    )
    assert result == "ok"
    attempts_after_reset = registry.get_sample_value(
        "security_tool_retry_attempts_total", labels={"tool": "demo"}
    )
    assert attempts_after_reset == 1.0
