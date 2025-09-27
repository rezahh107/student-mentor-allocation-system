from __future__ import annotations

import pytest
from datetime import datetime, timezone

from phase6_import_to_sabt.exporter import ExportValidationError
from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_counter_prefix_and_regex(tmp_path):
    row = make_row(idx=1, gender=1)
    row = row.__class__(**{**row.__dict__, "counter": "223733333"})
    exporter = build_exporter(tmp_path, [row])
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    with pytest.raises(ExportValidationError):
        exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))


def test_enums_and_phone(tmp_path):
    row = make_row(idx=2, center=5)
    exporter = build_exporter(tmp_path, [row])
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    with pytest.raises(ExportValidationError):
        exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
