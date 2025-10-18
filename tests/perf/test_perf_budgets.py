from __future__ import annotations

from repo_auditor_lite.__main__ import estimate_perf_budget


def test_analyze_perf_budget() -> None:
    budget = estimate_perf_budget(400)
    assert budget["p95_ms"] <= 200
    assert budget["memory_mb"] <= 150
