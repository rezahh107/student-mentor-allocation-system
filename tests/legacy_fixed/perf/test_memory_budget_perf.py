from __future__ import annotations

import gc
import resource
import sys
import tracemalloc
from pathlib import Path

from sma.phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from sma.phase6_import_to_sabt.obs.metrics import build_metrics


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


def test_rss_under_budget():
    gc.collect()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":  # pragma: no cover - macOS CI safeguard
        peak_mb = usage.ru_maxrss / (1024 * 1024)
    else:
        peak_mb = usage.ru_maxrss / 1024
    context = {
        "ru_maxrss": usage.ru_maxrss,
        "ru_ixrss": usage.ru_ixrss,
        "ru_idrss": usage.ru_idrss,
        "platform": sys.platform,
    }
    assert peak_mb < 300, context
