from __future__ import annotations

import filecmp
from datetime import datetime, timezone

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_repeatable_snapshot(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 4)]
    snapshot = ExportSnapshot(marker="snap", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    filters = ExportFilters(year=1402)
    options = ExportOptions(chunk_size=10)

    dir1 = tmp_path / "first"
    dir1.mkdir()
    exporter1 = build_exporter(dir1, rows)
    exporter1.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))

    dir2 = tmp_path / "second"
    dir2.mkdir()
    exporter2 = build_exporter(dir2, rows)
    exporter2.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))

    file1 = next(dir1.glob("*.csv"))
    file2 = next(dir2.glob("*.csv"))
    assert file1.read_bytes() == file2.read_bytes()
