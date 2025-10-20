import datetime as dt
from pathlib import Path

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _rows(year: int, center: int | None):
    return [
        {
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
            "year_code": str(year),
        }
    ]


def test_clock_timezone_is_asia_tehran(tmp_path: Path) -> None:
    clock = FixedClock(dt.datetime(2024, 1, 1, 0, 0, tzinfo=dt.timezone.utc))
    metrics = build_import_export_metrics()
    workflow = ImportToSabtWorkflow(storage_dir=tmp_path, clock=clock, metrics=metrics, data_provider=_rows)
    record = workflow.create_export(year=1402, center=None)
    assert record.manifest["generated_at"].endswith("+03:30")
