from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.compat import TestClient
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def test_post_get_flow_with_signed_urls(tmp_path):
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
        readiness_gate=gate,
    )
    client = TestClient(app)

    response = client.post(
        "/exports",
        json={"year": 1402, "center": 1, "format": "csv"},
        headers={"Idempotency-Key": "abc", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["middleware_chain"] == ["ratelimit", "idempotency", "auth"]

    runner.await_completion(data["job_id"])

    status = client.get(f"/exports/{data['job_id']}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "SUCCESS"
    assert payload["files"]
    assert payload["files"][0]["url"].startswith("https://files.local/export")
    assert payload["files"][0]["sha256"]
    assert payload["manifest"]["format"] == "csv"
    assert payload["manifest"]["excel_safety"]["always_quote"]
