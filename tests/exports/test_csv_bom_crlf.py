from __future__ import annotations

import codecs
import csv
from dataclasses import replace

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase7_release.deploy import ReadinessGate

from tests.export.helpers import build_job_runner, make_row


def _build_export_api(tmp_path, rows):
    runner, metrics = build_job_runner(tmp_path, rows)
    signer = HMACSignedURLProvider(secret="secret")
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    app = create_export_api(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=gate,
    )
    return app, runner, metrics


def test_bom_and_crlf_when_flag_true(tmp_path) -> None:
    """CSV exports honour Excel safety toggles and manifest semantics."""

    sample = replace(
        make_row(idx=1),
        first_name="=SUM(A1:A2)",
        mentor_name="@cmd",
        national_id="۱۲۳۴۵۶۷۸۹۰",
        mobile="۰۹۱۲۳۴۵۶۷۸۹",
    )
    app, runner, metrics = _build_export_api(tmp_path, [sample])
    client = TestClient(app)

    response = client.post(
        "/exports",
        json={"year": 1402, "center": 1, "format": "csv", "bom": True},
        headers={"Idempotency-Key": "idem-csv", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    runner.await_completion(job_id)

    status = client.get(f"/exports/{job_id}")
    assert status.status_code == 200
    payload = status.json()

    manifest = payload["manifest"]
    assert manifest["format"] == "csv"
    assert manifest["excel_safety"]["always_quote"]
    assert manifest["excel_safety"]["formula_guard"]

    file_name = manifest["files"][0]["name"]
    csv_path = tmp_path / file_name
    content = csv_path.read_bytes()
    assert content.startswith(codecs.BOM_UTF8)
    assert b"\r\n" in content

    decoded = content.decode("utf-8-sig")
    rows = [line for line in decoded.split("\r\n") if line]
    reader = csv.reader(rows)
    header = next(reader)
    data = next(reader)
    column_index = {name: idx for idx, name in enumerate(header)}

    assert data[column_index["first_name"]].startswith("'=")
    assert data[column_index["mentor_name"]].startswith("'@")

    data_line = rows[1]
    for sensitive in ("national_id", "counter", "mobile", "mentor_id", "school_code"):
        value = data[column_index[sensitive]]
        assert f'"{value}"' in data_line

    samples = metrics.duration_seconds.collect()[0].samples
    phases = {s.labels.get("phase") for s in samples if s.name.endswith("_count")}
    assert {"queue", "total"}.issubset(phases)
