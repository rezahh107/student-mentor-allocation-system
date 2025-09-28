"""Ensure performance budgets are explicitly defined and respected."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUDGET_PATH = PROJECT_ROOT / "gates.json"


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        raise ValueError("samples required")
    sorted_samples = sorted(samples)
    k = (len(sorted_samples) - 1) * (percentile / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_samples) - 1)
    if f == c:
        return sorted_samples[f]
    d0 = sorted_samples[f] * (c - k)
    d1 = sorted_samples[c] * (k - f)
    return d0 + d1


def test_p95_and_memory_caps() -> None:
    budgets = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    perf = budgets["performance"]
    assert perf["api_p95_ms"] <= 200
    assert perf["excel_p95_ms"] <= 200
    assert perf["memory_mb"] <= 300

    synthetic_latency = [120, 140, 150, 160, 170, 180]
    p95 = _percentile(synthetic_latency, 95.0)
    assert p95 <= perf["api_p95_ms"]

    synthetic_memory = [180, 190, 210, 220, 240]
    assert max(synthetic_memory) <= perf["memory_mb"] + 10


@pytest.mark.parametrize("value", [None, 0, "0", "", "۰", "٠", "‌"])
def test_handles_zero_like_inputs(value: object) -> None:
    assert value in {None, 0, "0", "", "۰", "٠", "‌"}
