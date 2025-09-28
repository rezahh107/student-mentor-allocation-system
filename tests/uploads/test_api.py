from __future__ import annotations

import hashlib


def _headers():
    return {
        "Idempotency-Key": "req-1",
        "X-Request-ID": "RID-1",
        "X-Namespace": "tests",
        "Authorization": "Bearer token",
    }


def test_post_upload_csv_ok(uploads_app, uploads_config):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,123,09123456789,0012345678,محمد,کاظمی\r\n"
    ).encode("utf-8")
    response = uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1402"},
        files={"file": ("roster.csv", csv_content, "text/csv")},
        headers={**_headers(), "X-Debug-Middleware": "1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    digest = hashlib.sha256(csv_content).hexdigest()
    stored_path = uploads_config.storage_dir / "sha256" / f"{digest}.csv"
    assert stored_path.exists()
    manifest = payload["manifest"]
    assert manifest["sha256"] == digest
    assert manifest["record_count"] == 1
    assert manifest["size_bytes"] == len(csv_content)
    assert payload["middleware_chain"] == ["rate", "idem", "auth"]


def test_get_upload_status_manifest(uploads_app):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "2,200,09100000000,0023456789,زهرا,کریمی\r\n"
    ).encode("utf-8")
    post = uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1401"},
        files={"file": ("file.csv", csv_content, "text/csv")},
        headers=_headers(),
    )
    upload_id = post.json()["id"]
    get = uploads_app.get(f"/uploads/{upload_id}")
    assert get.status_code == 200
    data = get.json()
    assert data["manifest"]["record_count"] == 1
    assert data["manifest"]["meta"]["year"] == 1401
