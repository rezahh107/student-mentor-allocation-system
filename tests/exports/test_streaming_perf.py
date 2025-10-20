from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_export_app, make_row


def test_memory_budget_and_chunking(tmp_path) -> None:
    rows = [make_row(idx=idx) for idx in range(1, 121)]
    app, runner, metrics = build_export_app(tmp_path, rows)
    client = TestClient(app)

    response = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "csv", "chunk_size": 50},
        headers={"Idempotency-Key": "idem-stream", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200, response.text
    manifest = response.json()["manifest"]
    files = manifest["files"]
    assert len(files) == 3
    for file_entry in files:
        assert file_entry["row_count"] <= 50

    bytes_metric = metrics.bytes_written_total.collect()[0]
    total_bytes = sum(sample.value for sample in bytes_metric.samples)
    assert total_bytes > 0

    runner.redis.flushdb()
    reset_registry(metrics.registry)
