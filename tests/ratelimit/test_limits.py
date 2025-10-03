from __future__ import annotations

import httpx
import pytest

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.errors import RATE_LIMIT_FA_MESSAGE
from phase6_import_to_sabt.security.rate_limit import RateLimitSettings
from phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def _ready_gate() -> ReadinessGate:
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    return gate


def _build_app(tmp_path):
    rows = [make_row(idx=1), make_row(idx=2)]
    runner, metrics = build_job_runner(tmp_path, rows)
    app = create_export_api(
        runner=runner,
        signer=HMACSignedURLProvider("secret"),
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=_ready_gate(),
    )
    return app, runner, metrics


@pytest.mark.asyncio
async def test_exceed_limit_persian_error(tmp_path) -> None:
    app, runner, metrics = _build_app(tmp_path)
    app.state.rate_limit_configure(RateLimitSettings(requests=1, window_seconds=60, penalty_seconds=120))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/exports",
            json={"year": 1402, "center": 1},
            headers={"Idempotency-Key": "rl-1", "X-Role": "ADMIN", "X-Client-ID": "limitee"},
        )
        assert first.status_code == 200, first.text
        second = await client.post(
            "/exports",
            json={"year": 1402, "center": 1},
            headers={"Idempotency-Key": "rl-2", "X-Role": "ADMIN", "X-Client-ID": "limitee"},
        )
    assert second.status_code == 429, second.text
    detail = second.json()["detail"]
    assert detail["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert detail["message"] == RATE_LIMIT_FA_MESSAGE
    assert int(second.headers["Retry-After"]) == 120
    limited_counter = metrics.rate_limit_total.labels(outcome="limited", reason="quota_exceeded")._value.get()
    assert limited_counter >= 1
    runner.await_completion(first.json()["job_id"])  # flush background thread


@pytest.mark.asyncio
async def test_config_snapshot_restore(tmp_path) -> None:
    app, _runner, _metrics = _build_app(tmp_path)
    snapshot = app.state.rate_limit_snapshot()
    app.state.rate_limit_configure(RateLimitSettings(requests=5, window_seconds=30, penalty_seconds=90))
    configured = app.state.export_rate_limiter.settings
    assert configured.requests == 5
    assert configured.window_seconds == 30
    app.state.rate_limit_restore(snapshot)
    restored = app.state.export_rate_limiter.settings
    assert restored.requests == snapshot.requests
    assert restored.window_seconds == snapshot.window_seconds
