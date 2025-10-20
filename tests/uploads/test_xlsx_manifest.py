import datetime as dt
from pathlib import Path

from openpyxl import Workbook

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def test_manifest_has_format_and_sha256(tmp_path: Path) -> None:
    wb = Workbook()
    sheet = wb.active
    sheet.append(["school_code"])
    sheet.append(["۱۲۳۴"])
    upload_file = tmp_path / "upload.xlsx"
    wb.save(upload_file)
    clock = FixedClock(dt.datetime(2024, 1, 1, 8, 30, tzinfo=dt.timezone.utc))
    metrics = build_import_export_metrics()

    def data_provider(year: int, center: int | None):  # pragma: no cover - uploads only
        return []

    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=metrics,
        data_provider=data_provider,
    )

    record = workflow.create_upload(profile="ROSTER_V1", year=1402, file_path=upload_file)
    assert record.manifest["format"] == "xlsx"
    assert "sha256" in record.manifest
    assert record.manifest_path.exists()
