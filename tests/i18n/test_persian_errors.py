from __future__ import annotations

import asyncio

import httpx
import pytest

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase6_import_to_sabt.errors import EXPORT_IO_FA_MESSAGE, EXPORT_VALIDATION_FA_MESSAGE
from sma.phase6_import_to_sabt.exporter import ExportIOError
from sma.phase6_import_to_sabt.models import ExportJobStatus
from sma.phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


@pytest.mark.asyncio
async def test_export_validation_error_message_exact(tmp_path) -> None:
    runner, metrics = build_job_runner(tmp_path, [make_row(idx=1)])
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    app = create_export_api(
        runner=runner,
        signer=HMACSignedURLProvider("secret"),
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=gate,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/exports",
            json={"year": 1402, "center": 1, "format": "pdf"},
            headers={"Idempotency-Key": "v-1", "X-Role": "ADMIN", "X-Client-ID": "validation"},
        )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "EXPORT_VALIDATION_ERROR"
    assert detail["message"] == EXPORT_VALIDATION_FA_MESSAGE


@pytest.mark.asyncio
async def test_export_io_error_message_exact(tmp_path, monkeypatch) -> None:
    runner, metrics = build_job_runner(tmp_path, [make_row(idx=1)])
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)

    def _fail_write(**kwargs):  # noqa: ANN001 - signature mirrors real method
        raise ExportIOError()

    monkeypatch.setattr(runner.exporter, "_write_exports", _fail_write)
    app = create_export_api(
        runner=runner,
        signer=HMACSignedURLProvider("secret"),
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=gate,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/exports",
            json={"year": 1402, "center": 1},
            headers={"Idempotency-Key": "io-1", "X-Role": "ADMIN", "X-Client-ID": "io"},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        await asyncio.to_thread(runner.await_completion, job_id)
        status = await client.get(
            f"/exports/{job_id}",
            headers={"X-Role": "ADMIN", "X-Client-ID": "io"},
        )
    payload = status.json()
    assert payload["status"] == ExportJobStatus.FAILED.value
    assert payload["error"]["error_code"] == "EXPORT_IO_ERROR"
    assert payload["error"]["message"] == EXPORT_IO_FA_MESSAGE
