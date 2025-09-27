from __future__ import annotations

from fastapi.testclient import TestClient

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from tests.export.helpers import build_job_runner, make_row


def test_ttl_and_semantics(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 5)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    app = create_export_api(runner=runner, signer=signer, metrics=metrics, logger=runner.logger)
    client = TestClient(app)

    missing_header = client.post("/exports", json={"year": 1402}, headers={"X-Role": "ADMIN"})
    assert missing_header.status_code == 422

    headers = {"Idempotency-Key": "idem-key", "X-Role": "ADMIN"}
    payload = {"year": 1402}
    first = client.post("/exports", json=payload, headers=headers)
    assert first.status_code == 200
    job_id = first.json()["job_id"]
    runner.await_completion(job_id)

    duplicate = client.post("/exports", json=payload, headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.json()["job_id"] == job_id

    redis_key = "phase6:exports:ADMIN:ALL:1402:idem-key"
    assert runner.redis.get_ttl(redis_key) == 86_400

    runner.redis.delete(redis_key)
    status = client.get(f"/exports/{job_id}")
    assert status.status_code == 200
