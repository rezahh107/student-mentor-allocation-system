from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_job_runner, make_row


def test_post_and_get_flow(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 4)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    app = create_export_api(runner=runner, signer=signer, metrics=metrics, logger=runner.logger)
    client = TestClient(app)

    response = client.post(
        "/exports",
        json={"year": 1402, "center": 1},
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
