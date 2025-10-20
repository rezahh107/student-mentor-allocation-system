import datetime as dt
import uuid

import asyncio
import httpx

from sma.phase6_import_to_sabt.app import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics
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


def test_exports_default_format_is_xlsx(tmp_path) -> None:
    unique = uuid.uuid4().hex
    app_config = AppConfig.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": f"test-{unique}", "operation_timeout": 0.2},
            "database": {"dsn": "postgresql://user:pass@localhost/db", "statement_timeout_ms": 500},
            "auth": {"metrics_token": "token", "service_token": "service"},
            "ratelimit": {"namespace": f"rl-{unique}", "requests": 5, "window_seconds": 60, "penalty_seconds": 120},
            "observability": {"service_name": "import-to-sabt", "metrics_namespace": f"import_to_sabt_{unique}"},
            "timezone": "Asia/Tehran",
        }
    )
    clock = FixedClock(dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc))
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    metrics = build_metrics(app_config.observability.metrics_namespace)
    ix_metrics = build_import_export_metrics()
    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=ix_metrics,
        data_provider=_rows,
    )
    rate_store = InMemoryKeyValueStore(namespace=f"rl-{unique}", clock=clock)
    idem_store = InMemoryKeyValueStore(namespace=f"idem-{unique}", clock=clock)
    readiness = {}
    app = create_application(
        app_config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes=readiness,
        workflow=workflow,
    )
    async def _invoke():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/exports",
                params={"year": 1402},
                headers={
                    "Authorization": "Bearer service",
                    "Idempotency-Key": "key-1",
                    "X-Client-ID": "client-1",
                },
            )

    response = asyncio.run(_invoke())
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "xlsx"
    assert workflow.get_export(payload["id"]).artifact_path.suffix == ".xlsx"
