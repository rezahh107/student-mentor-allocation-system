from __future__ import annotations

from sma.repo_doctor.exporter import stream_csv


def test_exporter_perf_budget() -> None:
    headers = ["national_id", "mobile", "full_name"]
    rows = (("0912345678", f"مشتری {i}", "علی") for i in range(100))
    csv_data, metrics = stream_csv(headers, rows)
    assert metrics.p95_latency_ms <= 200
    assert metrics.memory_peak_mb <= 300
    assert csv_data.count("\r\n") >= 101
