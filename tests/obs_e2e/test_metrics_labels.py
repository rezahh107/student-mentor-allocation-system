from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
import httpx
from prometheus_client import CollectorRegistry

from src.phase6_import_to_sabt.api import ExportAPI, ExportJobStatus, ExportLogger, ExporterMetrics
from src.phase7_release.deploy import ReadinessGate

from tests.phase7_utils import DummyJob, DummyRunner, FrozenClock


@pytest.fixture
def clean_state():
    yield


def _build_app(tmp_path):
    clock = FrozenClock(start=1.0)
    gate = ReadinessGate(clock=clock.monotonic, readiness_timeout=5)
    runner = DummyRunner(output_dir=tmp_path)
    runner.prime(DummyJob(id="job-obs", status=ExportJobStatus.SUCCESS.value))

    async def _probe() -> bool:
        return True

    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)
    api = ExportAPI(
        runner=runner,
        signer=lambda path, expires_in=0: path,
        metrics=metrics,
        logger=ExportLogger(),
        metrics_token="secret",
        readiness_gate=gate,
        redis_probe=_probe,
        db_probe=_probe,
    )
    app = FastAPI()
    app.include_router(api.create_router())
    return app, metrics


def _request(app: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async def _call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers)

    return asyncio.run(_call())


def test_metrics_include_format_label(tmp_path, clean_state):
    app, metrics = _build_app(tmp_path)
    metrics.observe_rows(5, format="csv")
    metrics.observe_file_bytes(1024, format="csv")
    response = _request(app, "/metrics", headers={"X-Metrics-Token": "secret"})
    assert response.status_code == 200
    payload = response.text
    assert 'export_rows_total{format="csv"}' in payload
    assert 'export_file_bytes_total{format="csv"}' in payload


def test_metrics_endpoint_rejects_missing_token(tmp_path, clean_state):
    app, _ = _build_app(tmp_path)
    forbidden = _request(app, "/metrics")
    assert forbidden.status_code == 403
    assert "دسترسی غیرمجاز" in forbidden.text
