from __future__ import annotations

import csv
from datetime import datetime, timezone

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_control_chars_removed(tmp_path):
    row = make_row(idx=1)
    dirty = row.__class__(**{**row.__dict__, "first_name": "Name\u200c\n\t"})
    exporter = build_exporter(tmp_path, [dirty])
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        row_out = next(reader)
    assert row_out["first_name"] == "Name"
