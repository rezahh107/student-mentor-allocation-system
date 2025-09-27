from __future__ import annotations

from datetime import datetime, timezone
import re

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_file_name_pattern(tmp_path):
    rows = [make_row(idx=1)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(chunk_size=10)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    assert re.match(r"export_SABT_V1_1402-1_\d{14}_001.csv", csv_path.name)
