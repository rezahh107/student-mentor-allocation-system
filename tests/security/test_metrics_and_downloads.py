from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
from starlette.requests import Request
from starlette.types import Scope

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase6_import_to_sabt.clock import FixedClock
from sma.phase6_import_to_sabt.download_api import (
    DownloadGateway,
    DownloadMetrics,
    DownloadRetryPolicy,
    DownloadSettings,
    create_download_router,
)
from sma.phase7_release.deploy import ReadinessGate
from tests.export.helpers import build_job_runner, make_row


def _ready_gate() -> ReadinessGate:
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    return gate


def test_metrics_token_guard_and_unsigned_download_rejected(tmp_path) -> None:
    rows = [make_row(idx=1)]
    runner, metrics = build_job_runner(tmp_path, rows)
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    signer = HMACSignedURLProvider(secret="secret", clock=FixedClock(now))
    app = create_export_api(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=runner.logger,
        metrics_token="metrics-token",
        readiness_gate=_ready_gate(),
    )
    download_router = create_download_router(
        settings=DownloadSettings(
            workspace_root=tmp_path,
            secret=b"download-secret",
            retry=DownloadRetryPolicy(),
        ),
        clock=runner.clock,
        metrics=DownloadMetrics(),
    )
    app.include_router(download_router)

    async def _exercise_metrics() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            unauthorized = await client.get("/metrics")
            assert unauthorized.status_code == 403
            authorized = await client.get(
                "/metrics", headers={"X-Metrics-Token": "metrics-token"}
            )
            assert authorized.status_code == 200

    asyncio.run(_exercise_metrics())

    gateway = DownloadGateway(
        settings=DownloadSettings(
            workspace_root=tmp_path,
            secret=b"download-secret",
            retry=DownloadRetryPolicy(),
        ),
        clock=runner.clock,
        metrics=DownloadMetrics(),
    )

    async def _invoke_download() -> tuple[int, bytes]:
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/download/not-a-token",
            "query_string": b"",
            "headers": [],
            "client": ("test", 0),
        }

        async def _receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive=_receive)
        response = await gateway.handle(request, "not-a-token")
        body = response.body if hasattr(response, "body") else b""
        return response.status_code, body

    status_code, body = asyncio.run(_invoke_download())
    assert status_code == 403
    payload = json.loads(body)
    assert payload.get("fa_error_envelope", {}).get("code") == "DOWNLOAD_INVALID_TOKEN"

    signed = signer.sign("/tmp/export.csv", expires_in=120)
    assert signer.verify(signed, now=now + timedelta(seconds=60))
    assert not signer.verify(signed, now=now + timedelta(seconds=121))
