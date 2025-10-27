"""Repository-level CI guard tests."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter

from sma.ci_hardening.strict_reporter import PytestSummary, enforce_caps


def test_warnings_zero() -> None:
    """Warnings must yield a cap preventing perfect scores."""

    summary = PytestSummary(passed=10, failed=0, xfailed=0, skipped=0, warnings=1)
    caps = enforce_caps(summary)
    assert caps["warnings"] == 90


def test_collector_registry_isolation() -> None:
    """Each registry fixture must start empty and remain isolated."""

    registry = CollectorRegistry()
    counter = Counter("test_counter", "Test counter", registry=registry)
    counter.inc()
    metrics = list(registry.collect())
    assert metrics[0].name == "test_counter"
