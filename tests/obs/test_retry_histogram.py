from __future__ import annotations

from datetime import datetime, timezone

from sma.core.retry import retry_backoff_seconds

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, make_row


def test_retry_histogram_present(tmp_path, monkeypatch) -> None:
    rows = [make_row(idx=i) for i in range(1, 4)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="csv")
    snapshot = ExportSnapshot(marker="retry", created_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    attempts = {"count": 0}

    original = exporter._write_exports

    def _flaky_write(**kwargs):  # noqa: ANN001
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("transient failure")
        return original(**kwargs)

    monkeypatch.setattr(exporter, "_write_exports", _flaky_write)
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=snapshot.created_at)
    histogram = retry_backoff_seconds.collect()[0].samples
    observed = [
        sample.value
        for sample in histogram
        if sample.name.endswith("_sum") and sample.labels.get("op") == "import_to_sabt.exporter.write"
    ]
    assert observed and observed[0] > 0.0
