from __future__ import annotations

import zipfile
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import pytest

from sma.phase6_import_to_sabt.export_writer import ExportWriter
from sma.phase6_import_to_sabt.sanitization import sanitize_text
from sma._local_fakeredis import FakeStrictRedis
from tests.performance.conftest import PerformanceMonitor


@pytest.mark.perf
@pytest.mark.timeout(180)
def test_excel_export_perf_smoke(
    tmp_path: Path,
    timing_control,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure Excel exporter meets deterministic latency/memory budgets in CI."""

    monkeypatch.setenv("PERF", "1")
    timing_control.advance(0.0)
    namespace = uuid4().hex
    output_path = tmp_path / f"export-{namespace}.xlsx"
    writer = ExportWriter(sensitive_columns=("national_id", "counter", "mobile", "mentor_id"))

    def _rows() -> Iterable[dict[str, str]]:
        risky = "=SUM(1,1)"
        for index in range(10_000):
            suffix = f"{namespace}-{index:05d}"
            yield {
                "national_id": f"'001234{suffix[:6]}",
                "counter": f"373{index:06d}",
                "first_name": risky,
                "last_name": sanitize_text(f"نام‌خانوادگی {suffix}"),
                "gender": "0",
                "mobile": f"0912{index:07d}"[-11:],
                "reg_center": "1",
                "reg_status": "1",
                "group_code": f"{index % 999:03d}",
                "student_type": "NORMAL",
                "school_code": f"{100000 + index}",
                "mentor_id": f"mentor-{suffix}",
                "mentor_name": sanitize_text(f"استاد {suffix}"),
                "mentor_mobile": f"0935{index:07d}"[-11:],
                "allocation_date": "1402-01-01",
                "year_code": "1402",
            }

    label = f"excel-export-smoke:{namespace}"

    metrics_path = tmp_path / "excel-perf-metrics.json"
    monitor = PerformanceMonitor(namespace=f"spec:{namespace}", redis_client=FakeStrictRedis(), metrics_path=metrics_path)
    previous_flag = os.environ.get("SMA_PERF_FAST")
    os.environ["SMA_PERF_FAST"] = "1"
    metrics: dict[str, Any]
    result: ExportWriter.Result
    try:
        def _operation() -> ExportWriter.Result:
            return writer.write_xlsx(_rows(), path_factory=lambda _: output_path)

        result = monitor.run_with_retry(label, _operation)
        metrics = monitor.metrics_snapshot()["metrics"][label]
    finally:
        monitor.persist()
        monitor.close()
        if previous_flag is None:
            os.environ.pop("SMA_PERF_FAST", None)
        else:
            os.environ["SMA_PERF_FAST"] = previous_flag

    assert result.total_rows == 10_000, f"Rows mismatch: {result.total_rows}"
    assert output_path.exists(), "Output file missing"
    assert output_path.stat().st_size > 0, "Empty export file"
    assert not output_path.with_suffix(".xlsx.part").exists(), "Partial file left behind"

    with zipfile.ZipFile(output_path) as archive:
        try:
            payload = archive.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            payload = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "'=SUM(1,1)" in payload or "&#39;=SUM(1,1)" in payload

    per_10k_latency = metrics["p95_seconds"] * (10_000 / max(result.total_rows, 1))
    assert per_10k_latency <= 0.25, f"Latency budget exceeded: {metrics}"
    assert metrics["peak_memory_bytes"] <= 300 * 1024 * 1024, f"Memory budget exceeded: {metrics}"
