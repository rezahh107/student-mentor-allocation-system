from __future__ import annotations

import asyncio

import httpx
import pytest

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def _ready_gate() -> ReadinessGate:
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    return gate


@pytest.mark.asyncio
async def test_middleware_order_get_paths(tmp_path) -> None:
    rows = [make_row(idx=1)]
    runner, metrics = build_job_runner(tmp_path, rows)
    app = create_export_api(
        runner=runner,
        signer=HMACSignedURLProvider("secret"),
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=_ready_gate(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        post = await client.post(
            "/exports",
            json={"year": 1402, "center": 1},
            headers={"Idempotency-Key": "mw-get", "X-Role": "ADMIN", "X-Client-ID": "chain"},
        )
        job_id = post.json()["job_id"]
        await asyncio.to_thread(runner.await_completion, job_id)
        status = await client.get(
            f"/exports/{job_id}",
            headers={"X-Role": "ADMIN", "X-Client-ID": "chain"},
        )
    assert status.status_code == 200
    assert status.json()["middleware_chain"] == ["ratelimit", "idempotency", "auth"]
