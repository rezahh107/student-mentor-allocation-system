from __future__ import annotations

from fastapi.testclient import TestClient

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from tests.export.helpers import build_job_runner, make_row


def test_error_messages_deterministic(tmp_path):
    runner, metrics = build_job_runner(tmp_path, [make_row(idx=1)])
    app = create_export_api(runner=runner, signer=HMACSignedURLProvider("secret"), metrics=metrics, logger=runner.logger)
    client = TestClient(app)
    response = client.post(
        "/exports",
        json={"year": 1402, "center": 1},
        headers={"Idempotency-Key": "k", "X-Role": "MANAGER"},
    )
    assert response.status_code == 400
    assert "کد مرکز" in response.json()["detail"]
