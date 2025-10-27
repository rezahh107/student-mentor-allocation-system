"""Prometheus metrics regression tests for uploads and exports."""

from __future__ import annotations

from typing import Iterable

from prometheus_client import CollectorRegistry

from sma.phase2_uploads.metrics import UploadsMetrics
from sma.phase6_import_to_sabt.metrics import ExporterMetrics, reset_registry


def _collect_samples(registry: CollectorRegistry, metric: str) -> Iterable[dict[str, str | float]]:
    collected = []
    for family in registry.collect():
        if family.name != metric:
            continue
        for sample in family.samples:
            labels = {**sample.labels}
            collected.append({"labels": labels, "value": sample.value})
    return collected


def test_upload_metrics_increment_and_errors_label_cardinality() -> None:
    """Uploads metrics must track successes, failures, and bytes with correct labels."""

    registry = CollectorRegistry()
    metrics = UploadsMetrics(registry)

    metrics.record_success("csv", duration=0.42, size=512)
    metrics.record_success("xlsx", duration=0.15, size=1024)
    metrics.record_failure("csv", "VALIDATION")

    success_csv = registry.get_sample_value(
        "uploads_total", {"status": "success", "format": "csv"}
    )
    success_xlsx = registry.get_sample_value(
        "uploads_total", {"status": "success", "format": "xlsx"}
    )
    failure_csv = registry.get_sample_value(
        "uploads_total", {"status": "failure", "format": "csv"}
    )
    error_validation = registry.get_sample_value(
        "upload_errors_total", {"type": "VALIDATION"}
    )

    assert success_csv == 1.0, f"Unexpected success count: {success_csv}"
    assert success_xlsx == 1.0, f"Unexpected xlsx count: {success_xlsx}"
    assert failure_csv == 1.0, f"Unexpected failure count: {failure_csv}"
    assert error_validation == 1.0, f"Unexpected error tally: {error_validation}"

    duration_samples = list(_collect_samples(registry, "upload_duration_seconds"))
    assert any(
        entry["labels"].get("phase") == "persist"
        for entry in duration_samples
    ), f"Missing persist phase observation: {duration_samples}"
    assert registry.get_sample_value("upload_file_bytes_total", {}) == 1536.0

    reset_registry(registry)


def test_export_metrics_track_phases_and_counts() -> None:
    """Exporter metrics must observe phases and counters for multiple formats."""

    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)

    metrics.observe_duration("prepare", 0.25, "csv")
    metrics.observe_duration("write", 0.5, "csv")
    metrics.observe_duration("finalize", 0.1, "csv")
    metrics.observe_duration("prepare", 0.3, "xlsx")

    metrics.observe_rows(100, "csv")
    metrics.observe_rows(50, "xlsx")
    metrics.observe_file_bytes(2048, "csv")
    metrics.observe_file_bytes(4096, "xlsx")

    metrics.inc_job("success", "csv")
    metrics.inc_job("failure", "csv")
    metrics.inc_job("success", "xlsx")
    metrics.inc_error("validation", "csv")
    metrics.inc_error("io", "xlsx")

    csv_success = registry.get_sample_value(
        "export_jobs_total", {"status": "success", "format": "csv"}
    )
    csv_failure = registry.get_sample_value(
        "export_jobs_total", {"status": "failure", "format": "csv"}
    )
    xlsx_success = registry.get_sample_value(
        "export_jobs_total", {"status": "success", "format": "xlsx"}
    )
    validation_errors = registry.get_sample_value(
        "export_errors_total", {"type": "validation", "format": "csv"}
    )
    io_errors = registry.get_sample_value(
        "export_errors_total", {"type": "io", "format": "xlsx"}
    )

    assert csv_success == 1.0 and csv_failure == 1.0, (
        f"CSV status counts unexpected: success={csv_success}, failure={csv_failure}"
    )
    assert xlsx_success == 1.0, f"XLSX success count mismatch: {xlsx_success}"
    assert validation_errors == 1.0, f"Validation errors mismatch: {validation_errors}"
    assert io_errors == 1.0, f"IO errors mismatch: {io_errors}"

    histogram_samples = list(_collect_samples(registry, "export_duration_seconds"))
    phases = {sample["labels"].get("phase") for sample in histogram_samples}
    assert {"prepare", "write", "finalize"}.issubset(phases), phases

    csv_rows = registry.get_sample_value("export_rows_total", {"format": "csv"})
    xlsx_rows = registry.get_sample_value("export_rows_total", {"format": "xlsx"})
    csv_bytes = registry.get_sample_value("export_file_bytes_total", {"format": "csv"})
    xlsx_bytes = registry.get_sample_value("export_file_bytes_total", {"format": "xlsx"})

    assert csv_rows == 100.0 and xlsx_rows == 50.0, (
        f"Row counters incorrect: csv={csv_rows}, xlsx={xlsx_rows}"
    )
    assert csv_bytes == 2048.0 and xlsx_bytes == 4096.0, (
        f"Byte counters incorrect: csv={csv_bytes}, xlsx={xlsx_bytes}"
    )

    reset_registry(registry)
