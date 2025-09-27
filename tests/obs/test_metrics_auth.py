from __future__ import annotations

from fastapi.testclient import TestClient

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.models import ExportFilters, ExportOptions
from tests.export.helpers import build_job_runner, make_row


def test_metrics_endpoint_guarded(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 4)]
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    app = create_export_api(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=runner.logger,
        metrics_token="token-123",
    )
    client = TestClient(app)

    forbidden = client.get("/metrics")
    assert forbidden.status_code == 403

    job = runner.submit(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(),
        idempotency_key="metrics",
        namespace="metrics",
    )
    runner.await_completion(job.id)

    allowed = client.get("/metrics", headers={"X-Metrics-Token": "token-123"})
    assert allowed.status_code == 200
    assert "export_jobs_total" in allowed.text
