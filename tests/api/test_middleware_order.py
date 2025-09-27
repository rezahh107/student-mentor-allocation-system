from __future__ import annotations

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


def test_rate_limit_idem_auth_order_all_routes(tmp_path, clean_state):
    client = _client(tmp_path)
    headers = {
        "X-Role": "ADMIN",
        "Idempotency-Key": "abc",
        "X-Metrics-Token": "secret",
    }
    create = client.post("/exports", json={"year": 1402}, headers=headers)
    assert create.status_code == 200
    assert create.json()["middleware_chain"] == ["ratelimit", "idempotency", "auth"]

    health = client.get("/healthz", headers=headers)
    assert health.status_code in {200, 503}
    assert health.json()["middleware_chain"] == ["ratelimit", "idempotency", "auth"]
