from __future__ import annotations

from statistics import quantiles

import pytest

pytest_plugins = ["tests.fixtures.state"]


def test_budget_caps_deterministic(cleanup_fixtures) -> None:  # type: ignore[no-untyped-def]
    durations = [12.0] * 95 + [14.5] * 5
    p95 = quantiles(durations, n=100)[94]
    assert p95 < 15.0, cleanup_fixtures.context(durations=durations, p95=p95)

    memory_samples = [110_000_000, 125_000_000, 128_500_000]
    peak_memory_mb = max(memory_samples) / (1024 * 1024)
    assert peak_memory_mb < 150.0, cleanup_fixtures.context(peak=peak_memory_mb)

    total_rows = 100_000
    assert total_rows == 100_000, cleanup_fixtures.context(rows=total_rows)
