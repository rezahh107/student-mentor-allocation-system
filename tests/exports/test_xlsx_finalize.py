import datetime as dt
from pathlib import Path

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _rows() -> list[dict[str, object]]:
    base = {
        "national_id": "001",
        "counter": "140257300",
        "first_name": "علی",
        "last_name": "رضایی",
        "gender": 0,
        "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
        "reg_center": 1,
        "reg_status": 1,
        "group_code": 5,
        "student_type": 0,
        "school_code": 123,
        "mentor_id": "m-1",
        "mentor_name": "Safe",
        "mentor_mobile": "09120000000",
        "allocation_date": "2023-01-01T00:00:00Z",
        "year_code": "1402",
    }
    return [dict(base, national_id=f"{i:03d}") for i in range(1, 4)]


def test_atomic_finalize_and_manifest(tmp_path: Path) -> None:
    clock = FixedClock(dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc))
    metrics = build_import_export_metrics()

    def data_provider(year: int, center: int | None):
        return list(_rows())

    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=metrics,
        data_provider=data_provider,
        chunk_size=2,
    )

    record = workflow.create_export(year=1402, center=None)
    assert record.manifest_path.exists()
    assert not any(tmp_path.glob("*.part"))
    manifest = record.manifest
    assert manifest["format"] == "xlsx"
    assert manifest["files"][0]["row_counts"] == {"Sheet_001": 2, "Sheet_002": 1}
