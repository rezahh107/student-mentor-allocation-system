from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.api import ExportAPI, ExportJobStatus, ExportLogger, ExporterMetrics
from sma.phase7_release.deploy import ReadinessGate

from tests.phase7_utils import DummyJob, DummyRunner, FrozenClock


@pytest.fixture
def clean_state():
    yield


def _client(tmp_path) -> TestClient:
    clock = FrozenClock(start=1.0)
    gate = ReadinessGate(clock=clock.monotonic, readiness_timeout=5)
    runner = DummyRunner(output_dir=tmp_path)
    runner.prime(DummyJob(id="job-1", status=ExportJobStatus.PENDING.value))
    async def _probe() -> bool:
        return True

    api = ExportAPI(
        runner=runner,
        signer=lambda path, expires_in=0: path,
        metrics=ExporterMetrics(),
        logger=ExportLogger(),
        metrics_token="secret",
        readiness_gate=gate,
        redis_probe=_probe,
        db_probe=_probe,
    )
    app = FastAPI()
    app.include_router(api.create_router())
    return TestClient(app)


def test_metrics_endpoint_guarded(tmp_path, clean_state):
    client = _client(tmp_path)
    forbidden = client.get("/metrics")
    assert forbidden.status_code == 403

    ok = client.get("/metrics", headers={"X-Metrics-Token": "secret"})
    assert ok.status_code == 200
    assert "export_jobs_total" in ok.text
