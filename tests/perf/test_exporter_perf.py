from __future__ import annotations

from pathlib import Path

from tooling.clock import Clock
from tooling.excel_export import ExcelSafeCSVExporter


def test_exporter_perf_budgets(tmp_path):
    clock = Clock()
    exporter = ExcelSafeCSVExporter(clock=clock, chunk_size=5000)
    columns = ["national_id", "counter", "mobile", "text_fields_desc", "year"]

    def row_iter():
        for idx in range(100_000):
            yield {
                "national_id": f"{idx:010d}",
                "counter": f"123573{idx:04d}"[-10:],
                "mobile": "09123456789",
                "text_fields_desc": "نمونه",
                "year": 2024,
            }

    path = tmp_path / "bulk.csv"
    exporter.export(row_iter(), columns, path)
    assert path.exists()
    assert clock.monotonic() <= 12
    assert path.stat().st_size > 0
