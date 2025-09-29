from __future__ import annotations

import anyio
from fastapi import Depends, FastAPI, Header
import httpx

from ops.config import OpsSettings, SLOThresholds
from ops.security import metrics_guard


def build_app() -> FastAPI:
    settings = OpsSettings(
        reporting_replica_dsn="postgresql://user:pass@localhost:5432/replica",
        metrics_read_token="metrics-token-123456",
        slo_thresholds=SLOThresholds(
            healthz_p95_ms=120,
            readyz_p95_ms=150,
            export_p95_ms=800,
            export_error_budget=42,
        ),
    )

    app = FastAPI()

    async def guard(metrics_read_token: str | None = Header(default=None, alias="X-Metrics-Token")) -> None:
        await metrics_guard(settings, metrics_read_token)

    @app.get("/metrics")
    async def metrics_endpoint(_: None = Depends(guard)):
        return {"ok": True}

    return app


def test_metrics_requires_token():
    app = build_app()

    async def _exercise(headers: dict[str, str] | None = None) -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics", headers=headers)
            return response.status_code

    unauthorized = anyio.run(_exercise)
    assert unauthorized == 401
    authorized = anyio.run(lambda: _exercise({"X-Metrics-Token": "metrics-token-123456"}))
    assert authorized == 200
