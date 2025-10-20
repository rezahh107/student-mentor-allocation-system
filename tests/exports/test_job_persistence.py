import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.job_runner import DeterministicRedis
from sma.phase6_import_to_sabt.xlsx.job_store import RedisExportJobStore
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _rows(year: int, center: int | None):
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
        "year_code": str(year),
    }
    return [base, {**base, "national_id": "002", "mentor_id": "m-2"}]


def _tehran_now(clock: FixedClock) -> str:
    return clock.now().astimezone(ZoneInfo("Asia/Tehran")).isoformat()


def test_persist_and_resume_job_metadata_redis(tmp_path) -> None:
    redis_client = DeterministicRedis()
    redis_client.flushdb()
    try:
        clock = FixedClock(dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc))
        metrics = build_import_export_metrics()
        namespace = f"jobtest:{uuid.uuid4().hex}"
        store = RedisExportJobStore(
            redis=redis_client,
            namespace=namespace,
            now=lambda: _tehran_now(clock),
            metrics=metrics,
            sleeper=lambda _: None,
        )
        workflow = ImportToSabtWorkflow(
            storage_dir=tmp_path,
            clock=clock,
            metrics=metrics,
            data_provider=_rows,
            job_store=store,
            sleeper=lambda _: None,
        )
        record = workflow.create_export(year=1402, center=2)
        persisted = store.load(record.id)
        assert persisted is not None, {
            "redis_keys": redis_client._store,  # type: ignore[attr-defined]
            "job_id": record.id,
        }
        assert persisted["status"] == "SUCCESS"
        assert persisted["files"][0]["rows"] == 2

        restart_store = RedisExportJobStore(
            redis=redis_client,
            namespace=namespace,
            now=lambda: _tehran_now(clock),
            metrics=metrics,
            sleeper=lambda _: None,
        )
        restarted = ImportToSabtWorkflow(
            storage_dir=tmp_path,
            clock=clock,
            metrics=metrics,
            data_provider=_rows,
            job_store=restart_store,
            sleeper=lambda _: None,
        )
        resumed = restarted.get_export(record.id)
        assert resumed is not None, {
            "redis_keys": redis_client._store,  # type: ignore[attr-defined]
            "job_id": record.id,
        }
        assert resumed.metadata["status"] == "SUCCESS"
        assert resumed.manifest["id"] == record.id
        assert any(item["sheet"] == "Sheet_001" for item in resumed.metadata["files"])
    finally:
        redis_client.flushdb()
