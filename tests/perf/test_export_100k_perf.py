from __future__ import annotations

import time
import json
from datetime import datetime, timezone
from pathlib import Path

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from tests.export.helpers import build_exporter, make_row


def test_p95_latency_and_memory_budget(tmp_path) -> None:
    base_time = datetime(2024, 3, 26, 4, 0, tzinfo=timezone.utc)
    rows = [make_row(idx=i) for i in range(1, 100_001)]
    exporter = build_exporter(tmp_path, rows)
    options = ExportOptions(chunk_size=50_000, output_format="csv")
    filters = ExportFilters(year=1402, center=1)
    snapshot = ExportSnapshot(marker="perf", created_at=base_time)

    import tracemalloc

    tracemalloc.start()
    start = time.perf_counter()
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=base_time)
    duration = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert duration <= 15.0, f"Export exceeded latency budget: {duration}s"
    assert peak <= 150 * 1024 * 1024, f"Export exceeded memory budget: {peak} bytes"

    payload = {
        "test_export_100k_perf": {
            "duration_seconds": duration,
            "peak_bytes": peak,
        }
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    report_path = tmp_path / "perf_compare.json"
    report_path.write_text(serialized, encoding="utf-8")
    repo_report = Path("reports") / "perf_compare.json"
    repo_report.parent.mkdir(parents=True, exist_ok=True)
    repo_report.write_text(serialized, encoding="utf-8")
