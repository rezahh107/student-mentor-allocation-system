from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncio
import httpx

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.clock import FixedClock
from phase7_release.deploy import ReadinessGate
from tests.export.helpers import build_job_runner, make_row


def _ready_gate() -> ReadinessGate:
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    return gate


def test_token_and_signed_url(tmp_path) -> None:
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
    async def _exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthorized = await client.get("/metrics")
            assert unauthorized.status_code == 403
            authorized = await client.get("/metrics", headers={"X-Metrics-Token": "metrics-token"})
            assert authorized.status_code == 200

    asyncio.run(_exercise())

    signed = signer.sign("/tmp/export.csv", expires_in=120)
    assert signer.verify(signed, now=now + timedelta(seconds=60))
    assert not signer.verify(signed, now=now + timedelta(seconds=121))
