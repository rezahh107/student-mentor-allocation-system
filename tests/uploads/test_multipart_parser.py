from __future__ import annotations

import uuid

from phase2_uploads.logging_utils import get_debug_context


def _base_headers():
    return {
        "Idempotency-Key": f"mp-{uuid.uuid4().hex}",
        "X-Request-ID": f"RID-{uuid.uuid4().hex}",
        "X-Namespace": "tests-multipart",
        "Authorization": "Bearer token",
    }


def test_reject_malformed_boundary_persian_error(uploads_app):
    boundary = "----broken-boundary"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"profile\"\r\n\r\n"
        "ROSTER_V1\r\n"
    ).encode("utf-8")
    headers = {
        **_base_headers(),
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": str(len(body)),
    }
    response = uploads_app.post("/uploads", headers=headers, content=body)
    assert response.status_code == 400, get_debug_context({"body_len": len(body)})
    payload = response.json()
    assert payload["code"] == "UPLOAD_MULTIPART_INVALID"
    assert payload["details"]["reason"] == "missing-closing-boundary"
    assert "درخواست نامعتبر" in payload["message"]


def test_reject_incomplete_part_headers(uploads_app):
    boundary = "----header-missing"
    csv_body = "student_id,school_code\r\n1,10\r\n"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"profile\"\r\n\r\n"
        "ROSTER_V1\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/csv\r\n\r\n"
        f"{csv_body}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    headers = {
        **_base_headers(),
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": str(len(body)),
    }
    response = uploads_app.post("/uploads", headers=headers, content=body)
    assert response.status_code == 400, get_debug_context({"headers": headers})
    payload = response.json()
    assert payload["code"] == "UPLOAD_MULTIPART_INVALID"
    assert payload["details"]["reason"] == "disposition-missing"
    assert payload["message"].startswith("درخواست نامعتبر")


def test_reject_multiple_files_when_single_expected(uploads_app):
    boundary = "----multi-file"
    csv_body = "student_id,school_code\r\n1,20\r\n"
    other_csv = "student_id,school_code\r\n2,30\r\n"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"profile\"\r\n\r\n"
        "ROSTER_V1\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"year\"\r\n\r\n"
        "1400\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"one.csv\"\r\n"
        "Content-Type: text/csv\r\n\r\n"
        f"{csv_body}\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"two.csv\"\r\n"
        "Content-Type: text/csv\r\n\r\n"
        f"{other_csv}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    headers = {
        **_base_headers(),
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": str(len(body)),
    }
    response = uploads_app.post("/uploads", headers=headers, content=body)
    assert response.status_code == 400, get_debug_context({"len": len(body)})
    payload = response.json()
    assert payload["code"] == "UPLOAD_MULTIPART_FILE_COUNT"
    assert payload["message"].startswith("درخواست نامعتبر")
