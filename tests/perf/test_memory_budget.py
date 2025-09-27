from __future__ import annotations

import tracemalloc
from pathlib import Path

from phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from phase6_import_to_sabt.obs.metrics import build_metrics


def test_memory_budget_under_load(tmp_path: Path):
    destination = tmp_path / "mem.csv"
    metrics = build_metrics("mem_test")

    def rows():
        for i in range(2000):
            yield {"name": f"کاربر {i}", "value": "1234567890" * 5}

    tracemalloc.start()
    write_csv_atomic(destination, rows(), header=["name", "value"], sensitive_fields=["value"], metrics=metrics)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metrics.reset()
    assert peak < 150 * 1024 * 1024
