from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase6_import_to_sabt.metrics import reset_registry
from tests.export.helpers import build_export_app, make_row


def test_parallel_requests_share_job(tmp_path) -> None:
    rows = [make_row(idx=idx) for idx in range(1, 61)]
    app, runner, metrics = build_export_app(tmp_path, rows)
    runner.redis.flushdb()
    params = {"year": 1402, "center": 1, "format": "csv", "chunk_size": 200}
    headers = {"Idempotency-Key": "concurrent-key", "X-Role": "ADMIN"}
    responses = []
    with TestClient(app) as client:
        responses.append(client.get("/export/sabt/v1", params=params, headers=headers))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(client.get, "/export/sabt/v1", params=params, headers=headers),
                executor.submit(client.get, "/export/sabt/v1", params=params, headers=headers),
            ]
            for future in futures:
                responses.append(future.result())
    try:
        assert all(resp.status_code == 200 for resp in responses), [resp.text for resp in responses]
        bodies = [resp.json() for resp in responses]
        job_ids = {body["job_id"] for body in bodies}
        assert len(job_ids) == 1
        manifest_rows = {body["manifest"]["total_rows"] for body in bodies}
        assert manifest_rows == {len(rows)}
        chains = {tuple(body["middleware_chain"]) for body in bodies}
        assert chains == {("ratelimit", "idempotency", "auth")}
        sort_samples = metrics.sort_rows_total.collect()[0].samples
        assert any(sample.labels.get("format") == "csv" and sample.value == len(rows) for sample in sort_samples)
        assert not list(tmp_path.glob("*.part"))
        workspace = tmp_path / ".sort_work"
        if workspace.exists():
            assert not list(workspace.rglob("*.chunk"))
    finally:
        runner.redis.flushdb()
        reset_registry(metrics.registry)
