from __future__ import annotations

import json
from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from tests.export.helpers import build_exporter, make_row


def test_manifest_written_after_atomic_finalize(tmp_path) -> None:
    base_time = datetime(2024, 3, 25, 5, 0, tzinfo=timezone.utc)
    orphan = tmp_path / "stale.csv.part"
    orphan.write_text("stale", encoding="utf-8")

    exporter = build_exporter(tmp_path, [make_row(idx=1), make_row(idx=2)])
    assert not orphan.exists(), "Orphan .part should be cleaned on init"

    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(chunk_size=1, output_format="csv"),
        snapshot=ExportSnapshot(marker="snap", created_at=base_time),
        clock_now=base_time,
    )

    assert not any(tmp_path.glob("*.part")), "Atomic writer should leave no .part files"
    manifest_path = tmp_path / "export_manifest.json"
    assert manifest_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == base_time.isoformat()
    assert payload["config"]["format"] == "csv"
    assert payload["config"]["crlf"] is True
    assert payload["metadata"]["sort_keys"] == [
        "year_code",
        "reg_center",
        "group_code",
        "school_code",
        "national_id",
    ]
    for file_meta in payload["files"]:
        assert len(file_meta["sha256"]) == 64, file_meta
        assert file_meta["row_count"] > 0
