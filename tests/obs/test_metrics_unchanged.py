from __future__ import annotations

from prometheus_client import CollectorRegistry

from sma.phase6_import_to_sabt.metrics import ExporterMetrics, reset_registry


def test_export_metrics_labels_present() -> None:
    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry=registry)
    metrics.inc_job("success", "csv")
    metrics.observe_duration("write", 0.1, "csv")
    metrics.observe_rows(25, "csv")
    metrics.observe_file_bytes(2048, "csv")
    metrics.inc_error("validation", "csv")

    assert registry.get_sample_value("export_jobs_total", {"status": "success", "format": "csv"}) == 1.0
    assert registry.get_sample_value("export_duration_seconds_sum", {"phase": "write", "format": "csv"}) == 0.1
    assert registry.get_sample_value("export_rows_total", {"format": "csv"}) == 25.0
    assert registry.get_sample_value("export_file_bytes_total", {"format": "csv"}) == 2048.0
    assert registry.get_sample_value("export_errors_total", {"type": "validation", "format": "csv"}) == 1.0

    reset_registry(registry)
    for metric in registry.collect():
        assert not list(metric.samples)

