from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from tests.export.helpers import build_exporter, make_row


def test_csv_crlf_and_bom_behavior(tmp_path) -> None:
    base_time = datetime(2024, 3, 20, 10, 15, tzinfo=timezone.utc)
    rows = [make_row(idx=1), make_row(idx=2)]

    exporter_with_bom = build_exporter(tmp_path / "with_bom", rows)
    manifest_with_bom = exporter_with_bom.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(chunk_size=10, include_bom=True, output_format="csv"),
        snapshot=ExportSnapshot(marker="snap", created_at=base_time),
        clock_now=base_time,
    )

    csv_path_with_bom = (tmp_path / "with_bom" / manifest_with_bom.files[0].name)
    payload_with_bom = csv_path_with_bom.read_bytes()
    assert payload_with_bom.startswith(b"\xef\xbb\xbf"), f"Missing BOM; context={csv_path_with_bom}"
    assert payload_with_bom.endswith(b"\r\n"), f"CRLF not enforced; context={csv_path_with_bom}"
    assert manifest_with_bom.metadata["config"]["csv_bom"] is True
    assert manifest_with_bom.metadata["config"]["crlf"] is True

    exporter_without_bom = build_exporter(tmp_path / "no_bom", rows)
    manifest_without_bom = exporter_without_bom.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(chunk_size=10, include_bom=False, output_format="csv"),
        snapshot=ExportSnapshot(marker="snap", created_at=base_time),
        clock_now=base_time,
    )

    csv_path_without_bom = (tmp_path / "no_bom" / manifest_without_bom.files[0].name)
    payload_without_bom = csv_path_without_bom.read_bytes()
    assert not payload_without_bom.startswith(b"\xef\xbb\xbf"), "Unexpected BOM for CSV without flag"
    assert payload_without_bom.endswith(b"\r\n"), f"CRLF missing; context={csv_path_without_bom}"
    assert manifest_without_bom.metadata["config"]["csv_bom"] is False
    assert manifest_without_bom.metadata["config"]["crlf"] is True
