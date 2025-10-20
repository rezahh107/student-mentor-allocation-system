from __future__ import annotations

import httpx
import pytest

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def _ready_gate() -> ReadinessGate:
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    return gate


@pytest.mark.asyncio
async def test_middleware_order_post_exports_xlsx(tmp_path) -> None:
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
        response = await client.post(
            "/exports",
            json={"year": 1402, "center": 1, "format": "xlsx"},
            headers={"Idempotency-Key": "mw-1", "X-Role": "ADMIN", "X-Client-ID": "order"},
        )
    assert response.status_code == 200
    assert response.json()["middleware_chain"] == ["ratelimit", "idempotency", "auth"]
