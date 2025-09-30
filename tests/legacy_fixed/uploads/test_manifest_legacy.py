from __future__ import annotations

import json


def test_manifest_contains_sha256_counts_meta(uploads_app, uploads_config):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,123,09123456789,0012345678,لیلا,حسنی\r\n"
    ).encode("utf-8")
    response = uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1403"},
        files={"file": ("manifest.csv", csv_content, "text/csv")},
        headers={
            "Idempotency-Key": "manifest-1",
            "X-Request-ID": "RID-manifest",
            "X-Namespace": "manifests",
            "Authorization": "Bearer token",
        },
    )
    payload = response.json()
    upload_id = payload["id"]
    manifest_path = (
        uploads_config.manifest_dir / "manifests" / f"{upload_id}_upload_manifest.json"
    )
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["record_count"] == 1
    assert manifest["meta"]["profile"] == "ROSTER_V1"
    assert manifest["meta"]["year"] == 1403
    assert manifest["sha256"] == payload["manifest"]["sha256"]
    assert manifest["generated_at"].endswith("+04:00")
