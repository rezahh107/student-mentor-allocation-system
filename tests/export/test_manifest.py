from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from phase6_import_to_sabt.exporter import ImportToSabtExporter
from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_manifest_sha_and_totals(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 6)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402, center=None)
    options = ExportOptions(chunk_size=2, include_bom=False)
    snapshot = ExportSnapshot(marker="snapshot", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    manifest = exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    assert manifest.total_rows == 5
    manifest_path = next(tmp_path.glob("manifest_*.json"))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["total_rows"] == 5
    first_file = tmp_path / data["files"][0]["name"]
    import hashlib

    sha = hashlib.sha256(first_file.read_bytes()).hexdigest()
    assert data["files"][0]["sha256"] == sha
