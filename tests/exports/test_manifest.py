from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, make_row


def test_atomic_manifest_after_files(tmp_path: Path) -> None:
    rows = [make_row(idx=i) for i in range(1, 4)]
    exporter = build_exporter(tmp_path, rows)
    snapshot = ExportSnapshot(marker="snapshot", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(chunk_size=2, output_format="csv"),
        snapshot=snapshot,
        clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc),
    )

    manifest_path = tmp_path / "export_manifest.json"
    assert manifest_path.exists()
    assert not any(tmp_path.glob("*.part"))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["files"]
    for entry in payload["files"]:
        file_path = tmp_path / entry["name"]
        sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert entry["sha256"] == sha256
    assert manifest.total_rows == 3
    assert manifest.format == "csv"
    assert manifest.excel_safety["always_quote"] is True
