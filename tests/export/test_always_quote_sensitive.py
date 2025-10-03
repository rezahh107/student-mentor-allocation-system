from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot, SABT_V1_PROFILE
from tests.export.helpers import build_exporter, make_row


def test_sensitive_columns_always_quoted_csv(tmp_path) -> None:
    base_time = datetime(2024, 3, 22, 9, 0, tzinfo=timezone.utc)
    row = make_row(idx=7)
    exporter = build_exporter(tmp_path, [row])
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv"),
        snapshot=ExportSnapshot(marker="snap", created_at=base_time),
        clock_now=base_time,
    )

    csv_path = tmp_path / manifest.files[0].name
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header = [cell.strip("\"") for cell in lines[0].split(",")]
    data = lines[1].split(",")
    for column in SABT_V1_PROFILE.sensitive_columns:
        idx = header.index(column)
        field = data[idx]
        assert field.startswith("\"") and field.endswith("\""), (
            f"Sensitive column {column} not quoted; line={data}"
        )
