from __future__ import annotations

from fastapi.testclient import TestClient

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from tests.export.helpers import build_job_runner, make_row


def test_rate_limit_idem_auth_order(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 3)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    app = create_export_api(runner=runner, signer=signer, metrics=metrics, logger=runner.logger)
    client = TestClient(app)

    response = client.post(
        "/exports",
        json={"year": 1402, "center": 1},
        headers={"Idempotency-Key": "order", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200
    chain = response.json()["middleware_chain"]
    assert chain == ["ratelimit", "idempotency", "auth"]
