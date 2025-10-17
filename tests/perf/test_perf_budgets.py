from __future__ import annotations

from observability.metrics import PerformanceBudgets, PerformanceMonitor, create_metrics, reset_registry


def test_p95_latency_and_memory_budget() -> None:
    budgets = PerformanceBudgets(exporter_p95_seconds=0.2, signing_p95_seconds=0.2, memory_peak_mb=300.0)
    metrics = create_metrics("test_perf")
    monitor = PerformanceMonitor(metrics=metrics, budgets=budgets)
    exporter_samples = [0.05, 0.06, 0.07, 0.08, 0.09]
    signing_samples = [0.01, 0.015, 0.02, 0.025, 0.03]
    for duration in exporter_samples:
        monitor.record_export(duration=duration, memory_bytes=50 * 1024 * 1024)
    for duration in signing_samples:
        monitor.record_signing(duration=duration, memory_bytes=45 * 1024 * 1024)
    monitor.record_retry("export", attempts=2, exhausted=False)
    summary = monitor.ensure_within_budget()
    assert summary["exporter_p95"] <= budgets.exporter_p95_seconds
    assert summary["signing_p95"] <= budgets.signing_p95_seconds
    assert summary["memory_peak_mb"] <= budgets.memory_peak_mb
    reset_registry(metrics.registry)

