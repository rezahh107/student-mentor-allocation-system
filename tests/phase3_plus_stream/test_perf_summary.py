from pathlib import Path

from src.observe.perf import PerfSummary, PerformanceObserver


def test_perf_summary_json_roundtrip(tmp_path: Path) -> None:
    observer = PerformanceObserver()
    with observer.measure("alloc"):
        pass
    observer.increment_counter("allocation_policy_pass_total{rule='TEST'}")
    summary = observer.summary()
    output = tmp_path / "metrics.json"
    summary.to_json(output)
    loaded = PerfSummary.from_json(output)
    assert loaded.counters == summary.counters
    assert loaded.durations.keys() == summary.durations.keys()
    stats = loaded.stats()
    assert "alloc" in stats
    assert stats["alloc"].count == 1


def test_perf_summary_merge(tmp_path: Path) -> None:
    observer_a = PerformanceObserver()
    observer_b = PerformanceObserver()
    with observer_a.measure("alloc"):
        pass
    with observer_b.measure("alloc"):
        pass
    observer_a.increment_counter("x")
    observer_b.increment_counter("x")
    merged = PerformanceObserver.merge([observer_a.summary(), observer_b.summary()])
    stats = merged.stats()["alloc"]
    assert stats.count == 2
    assert merged.counters["x"] == 2
