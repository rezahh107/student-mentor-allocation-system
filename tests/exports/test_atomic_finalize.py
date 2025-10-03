import json

from phase6_import_to_sabt.compat import TestClient
from phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_export_app, make_row


def test_write_part_fsync_rename_manifest(tmp_path) -> None:
    rows = [make_row(idx=idx) for idx in range(1, 4)]
    app, runner, metrics = build_export_app(tmp_path, rows)
    client = TestClient(app)

    response = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "xlsx"},
        headers={"Idempotency-Key": "idem-atomic", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert not list(tmp_path.glob("*.part")), f"Leftover partial files: {list(tmp_path.glob('*.part'))}"

    manifest_file = tmp_path / "export_manifest.json"
    assert manifest_file.exists()
    manifest_payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_payload["total_rows"] == 3
    assert manifest_payload["format"] == "xlsx"
    files = manifest_payload["files"]
    assert files, "Manifest missing files"
    for item in files:
        assert int(item["row_count"]) > 0
        assert item["sha256"]

    response_manifest = payload["manifest"]
    assert response_manifest["files"][0]["byte_size"] > 0

    runner.redis.flushdb()
    reset_registry(metrics.registry)
