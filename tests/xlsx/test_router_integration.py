from __future__ import annotations

import asyncio
import datetime as dt
import io
import uuid

import httpx
from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig, AuthConfig, RateLimitConfig, RedisConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _rows(year: int, center: int | None) -> list[dict[str, object]]:
    return [
        {
            "national_id": "001",
            "counter": "140257300",
            "first_name": "علی",
            "last_name": "رضایی",
            "gender": 0,
            "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
            "reg_center": center or 1,
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


def _build_app(tmp_path, namespace: str) -> tuple:
    metric_namespace = namespace.replace("-", "_")
    metrics = build_metrics(metric_namespace)
    clock = FixedClock(dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc))
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    rate_store = InMemoryKeyValueStore(namespace=f"rate:{namespace}", clock=clock)
    idem_store = InMemoryKeyValueStore(namespace=f"idem:{namespace}", clock=clock)
    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path / namespace,
        clock=clock,
        metrics=build_import_export_metrics(),
        data_provider=_rows,
    )
    config = AppConfig(
        redis=RedisConfig(namespace=namespace),
        auth=AuthConfig(metrics_token="metrics-token", service_token="service-token"),
        ratelimit=RateLimitConfig(namespace=namespace, requests=10, window_seconds=60, penalty_seconds=60),
    )
    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
        workflow=workflow,
    )
    return app, workflow


def test_xlsx_upload_and_retrieve(tmp_path) -> None:
    namespace = f"xlsx-{uuid.uuid4().hex}"
    app, workflow = _build_app(tmp_path, namespace)
    assert app.state.xlsx_workflow is workflow
    workflow._upload_reader = type(
        "StubUploadReader",
        (),
        {
            "read": staticmethod(
                lambda path: type(
                    "Result",
                    (),
                    {
                        "format": "xlsx",
                        "rows": [],
                        "excel_safety": {},
                        "row_counts": {},
                    },
                )()
            ),
        },
    )()
    upload_source = tmp_path / "seed.xlsx"
    upload_source.write_bytes(b"Sample content")
    record = workflow.create_upload(profile="demo", year=1402, file_path=upload_source)
    with TestClient(app) as client:
        response = client.get(
            f"/api/xlsx/uploads/{record.id}",
            headers={"Authorization": "Bearer service-token", "X-RateLimit-Key": namespace},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
    assert payload["manifest"]["filters"]["year"] == 1402

    


def test_xlsx_export_handles_digit_inputs(tmp_path) -> None:
    namespace = f"xlsx-{uuid.uuid4().hex}"
    app, workflow = _build_app(tmp_path, namespace)

    async def _invoke() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/xlsx/exports",
                params={"year": 1402, "center": "۰"},
                headers={
                    "Authorization": "Bearer service-token",
                    "Idempotency-Key": f"export-{namespace}",
                    "X-RateLimit-Key": namespace,
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["format"] == "xlsx"
            assert payload["middleware_chain"][:3] == ["RateLimit", "Idempotency", "Auth"]
            return payload

    result = asyncio.run(_invoke())
    assert result["metadata"]["status"] == "SUCCESS"
    assert workflow.get_export(result["id"]).files
