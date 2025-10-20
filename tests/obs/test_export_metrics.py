from __future__ import annotations

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def test_export_metrics_labels_and_token_guard(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 4)]
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
        metrics_token="metrics-secret",
        readiness_gate=gate,
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/exports",
            json={"year": 1402, "center": None, "format": "csv"},
            headers={"Idempotency-Key": "m1", "X-Role": "ADMIN"},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        runner.await_completion(job_id)

        forbidden = client.get("/metrics")
        assert forbidden.status_code == 403

        ok = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})
        assert ok.status_code == 200
        metrics_body = ok.text
        assert 'format="csv"' in metrics_body
    finally:
        client.close()
