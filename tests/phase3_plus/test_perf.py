from __future__ import annotations

from src.observe.perf import PerformanceObserver


def test_measure_records_samples() -> None:
    observer = PerformanceObserver()
    for _ in range(3):
        with observer.measure("operation"):
            total = sum(range(100))
            assert total >= 0
    stats = observer.stats("operation")
    assert stats is not None
    assert stats.count == 3
    assert stats.max_ms >= 0
    assert stats.memory_peak_bytes >= 0


def test_counters_snapshot() -> None:
    observer = PerformanceObserver()
    observer.increment_counter("metric", amount=2)
    observer.increment_counter("metric")
    observer.increment_counter("other", amount=5)
    counters = observer.counters_snapshot()
    assert counters["metric"] == 3
    assert counters["other"] == 5


def test_stats_snapshot_contains_label() -> None:
    observer = PerformanceObserver()
    with observer.measure("label"):
        sum(range(10))
    snapshot = observer.stats_snapshot()
    assert "label" in snapshot
