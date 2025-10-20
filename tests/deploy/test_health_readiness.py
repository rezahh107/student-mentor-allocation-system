from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.api import ExportAPI, ExportJobStatus, ExportLogger, ExporterMetrics
from sma.phase7_release.deploy import ReadinessGate

from tests.phase7_utils import DummyJob, DummyRunner, FrozenClock


@pytest.fixture
def clean_state():
    yield


@dataclass
class ProbeState:
    result: bool

    async def __call__(self) -> bool:
        await asyncio.sleep(0)
        return self.result


def _build_client(tmp_path, readiness_gate: ReadinessGate, redis_probe, db_probe) -> TestClient:
    runner = DummyRunner(output_dir=tmp_path)
    runner.prime(DummyJob(id="job-1", status=ExportJobStatus.PENDING.value))
    api = ExportAPI(
        runner=runner,
        signer=lambda path, expires_in=0: path,
        metrics=ExporterMetrics(),
        logger=ExportLogger(),
        metrics_token="secret",
        readiness_gate=readiness_gate,
        redis_probe=redis_probe,
        db_probe=db_probe,
    )
    app = FastAPI()
    app.include_router(api.create_router())
    client = TestClient(app)
    return client


def test_health_ok_and_fail_modes(tmp_path, clean_state):
    clock = FrozenClock(start=1.0)
    gate = ReadinessGate(clock=clock.monotonic, readiness_timeout=10)
    redis_probe = ProbeState(result=True)
    db_probe = ProbeState(result=True)
    client = _build_client(tmp_path, gate, redis_probe, db_probe)

    response = client.get(
        "/healthz",
        headers={"X-Role": "ADMIN", "Idempotency-Key": "abc", "X-Metrics-Token": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    redis_probe.result = False
    response = client.get(
        "/healthz",
        headers={"X-Role": "ADMIN", "Idempotency-Key": "abc"},
    )
    assert response.status_code == 503
    payload = response.json()["detail"]
    assert payload["message"].startswith("وضعیت سامانه")


def test_readiness_gate_blocks_until_ready(tmp_path, clean_state):
    clock = FrozenClock(start=1.0)
    gate = ReadinessGate(clock=clock.monotonic, readiness_timeout=5)
    redis_probe = ProbeState(result=True)
    db_probe = ProbeState(result=True)
    client = _build_client(tmp_path, gate, redis_probe, db_probe)

    response = client.get(
        "/readyz",
        headers={"X-Role": "ADMIN", "Idempotency-Key": "abc"},
    )
    assert response.status_code == 503

    gate.record_cache_warm()
    response = client.get(
        "/readyz",
        headers={"X-Role": "ADMIN", "Idempotency-Key": "abc"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
