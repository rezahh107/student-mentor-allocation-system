from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from tests.export.helpers import build_exporter, make_row


def test_cleanup_and_registry_reset(tmp_path) -> None:
    base_time = datetime(2024, 3, 27, 3, 0, tzinfo=timezone.utc)
    orphan = tmp_path / "stuck.xlsx.part"
    orphan.write_text("pending", encoding="utf-8")

    rows = [make_row(idx=1), make_row(idx=2)]
    exporter = build_exporter(tmp_path, rows)
    assert not orphan.exists(), "Exporter should remove stale .part files during init"

    exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(chunk_size=1, output_format="xlsx"),
        snapshot=ExportSnapshot(marker="snap", created_at=base_time),
        clock_now=base_time,
    )

    leftover = list(tmp_path.glob("*.part"))
    assert not leftover, f"Unexpected partial artifacts: {leftover}"
