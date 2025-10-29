from __future__ import annotations

from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from tests.export.helpers import build_job_runner, make_row


def test_parallel_posts_one_job_ttl_24h(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 5)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    app = create_export_api(runner=runner, signer=signer, metrics=metrics, logger=runner.logger)
    with TestClient(app) as client:
        missing_header = client.post("/exports", json={"year": 1402}, headers={"X-Role": "ADMIN"})
        assert missing_header.status_code in {400, 422}

        headers = {"Idempotency-Key": "idem-key", "X-Role": "ADMIN"}
        payload = {"year": 1402}

        first_response = client.post("/exports", json=payload, headers=headers)
        second_response = client.post("/exports", json=payload, headers=headers)
        job_id = first_response.json()["job_id"]
        assert first_response.status_code == 202
        assert second_response.status_code in {200, 202}
        assert second_response.json()["job_id"] == job_id
        runner.await_completion(job_id)

        duplicate_ids = {job_id, second_response.json()["job_id"]}
        assert duplicate_ids == {job_id}

        redis_key = "phase6:exports:ADMIN:ALL:1402:idem-key"
        assert runner.redis.get_ttl(redis_key) == 86_400

        runner.redis.delete(redis_key)
        status_response = client.get(f"/exports/{job_id}")
        assert status_response.status_code == 200
