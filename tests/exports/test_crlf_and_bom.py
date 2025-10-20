import codecs

from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_export_app, make_row


def test_crlf_and_optional_bom(tmp_path) -> None:
    rows = [make_row(idx=idx) for idx in range(1, 3)]
    app, runner, metrics = build_export_app(tmp_path, rows)
    client = TestClient(app)

    with_bom = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "csv", "bom": True},
        headers={"Idempotency-Key": "idem-bom", "X-Role": "ADMIN"},
    )
    assert with_bom.status_code == 200, with_bom.text
    manifest = with_bom.json()["manifest"]
    bom_name = manifest["files"][0]["name"]
    bom_bytes = (tmp_path / bom_name).read_bytes()
    assert bom_bytes.startswith(codecs.BOM_UTF8)
    assert b"\r\n" in bom_bytes

    without_bom = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "csv", "bom": False},
        headers={"Idempotency-Key": "idem-nobom", "X-Role": "ADMIN"},
    )
    assert without_bom.status_code == 200, without_bom.text
    manifest_plain = without_bom.json()["manifest"]
    plain_name = manifest_plain["files"][0]["name"]
    plain_bytes = (tmp_path / plain_name).read_bytes()
    assert not plain_bytes.startswith(codecs.BOM_UTF8)
    assert b"\r\n" in plain_bytes

    runner.redis.flushdb()
    reset_registry(metrics.registry)
