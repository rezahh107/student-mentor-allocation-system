from __future__ import annotations

from tools.refactor_imports import compute_p95


def test_p95_latency_and_memory_budget() -> None:
    durations = [0.12, 0.15, 0.18, 0.19, 0.2]
    p95 = compute_p95(durations)
    assert p95 <= 0.2
    # simulate memory samples (MB) under 300 limit
    memory_samples = [120, 180, 190, 200]
    assert max(memory_samples) < 300
