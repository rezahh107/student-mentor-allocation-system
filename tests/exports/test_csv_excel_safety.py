import codecs
import csv
from dataclasses import replace

from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_export_app, make_row


def test_always_quote_and_formula_guard(tmp_path) -> None:
    sample = replace(
        make_row(idx=1),
        first_name="\u200c=SUM(A1:A2)",
        mentor_name="@cmd",
        national_id="۱۲۳۴۵۶۷۸۹۰",
        mobile="٠٩١٢٣٤٥٦٧٨٩",
    )
    app, runner, metrics = build_export_app(tmp_path, [sample])
    client = TestClient(app)

    response = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "csv", "bom": True},
        headers={"Idempotency-Key": "idem-csv-sabt", "X-Role": "ADMIN", "X-Request-ID": "req-1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    manifest = payload["manifest"]
    assert manifest["format"] == "csv"
    assert manifest["excel_safety"]["formula_guard"]
    assert manifest["excel_safety"]["normalized"]

    file_name = manifest["files"][0]["name"]
    csv_path = tmp_path / file_name
    content = csv_path.read_bytes()
    assert content.startswith(codecs.BOM_UTF8)
    decoded = content.decode("utf-8-sig")
    rows = [line for line in decoded.split("\r\n") if line]
    reader = csv.reader(rows)
    header = next(reader)
    data = next(reader)
    column_index = {name: idx for idx, name in enumerate(header)}

    assert data[column_index["first_name"]].startswith("'=")
    assert data[column_index["mentor_name"]].startswith("'@")
    assert data[column_index["national_id"]] == "1234567890"
    assert data[column_index["mobile"]] == "09123456789"
    assert data[column_index["counter"]][2:5] == "373"

    line = rows[1]
    for sensitive in ("national_id", "counter", "mobile", "mentor_id", "school_code"):
        value = data[column_index[sensitive]]
        assert f'"{value}"' in line

    runner.redis.flushdb()
    reset_registry(metrics.registry)
