from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_atomic_rename_and_fsync(tmp_path):
    exporter = build_exporter(tmp_path, [make_row(idx=1)])
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="snap", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    assert not list(tmp_path.glob("*.part"))
    assert any(tmp_path.glob("*.csv"))
