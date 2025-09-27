from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.phase6_import_to_sabt.api import ExportAPI, ExportJobStatus, ExportLogger, ExporterMetrics
from src.phase7_release.deploy import ReadinessGate

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
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    gate.record_cache_warm()
    app = FastAPI()
    app.include_router(api.create_router())
    return TestClient(app)


def test_healthz_under_budget(tmp_path, clean_state):
    client = _client(tmp_path)
    start = time.perf_counter()
    response = client.get(
        "/healthz",
        headers={"X-Role": "ADMIN", "Idempotency-Key": "abc"},
    )
    duration = time.perf_counter() - start
    assert response.status_code == 200
    assert duration < 0.5
