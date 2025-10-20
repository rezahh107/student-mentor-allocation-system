from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics


def test_export_metrics_have_format_label() -> None:
    metrics = build_import_export_metrics()
    metrics.export_jobs_total.labels(status="success", format="xlsx").inc()
    metrics.export_rows_total.labels(format="xlsx").inc(10)
    jobs_samples = metrics.export_jobs_total.collect()[0].samples
    assert all("format" in sample.labels for sample in jobs_samples)
    rows_samples = metrics.export_rows_total.collect()[0].samples
    assert all(sample.labels["format"] == "xlsx" for sample in rows_samples)
