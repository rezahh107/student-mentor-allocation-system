from __future__ import annotations

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def test_mw_order_rate_idem_auth(tmp_path):
    rows = [make_row(idx=1)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    app = create_export_api(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=gate,
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/exports",
            json={"year": 1402, "center": 1, "format": "csv"},
            headers={"Idempotency-Key": "chain", "X-Role": "ADMIN"},
        )
        assert response.status_code == 200
        assert response.json()["middleware_chain"] == ["ratelimit", "idempotency", "auth"]
    finally:
        client.close()
