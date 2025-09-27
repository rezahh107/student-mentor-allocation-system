from __future__ import annotations

import time
from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, make_row


def test_100k_under_budgets(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 100_001)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="perf", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    start = time.perf_counter()
    exporter.run(filters=filters, options=ExportOptions(chunk_size=50_000), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    duration = time.perf_counter() - start
    assert duration < 15
    assert sum(f.stat().st_size for f in tmp_path.glob("*.csv")) < 150 * 1024 * 1024
