from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from sma.phase2_uploads.errors import UploadError


HEADERS = {
    "Idempotency-Key": "activate-1",
    "X-Request-ID": "RID-act-1",
    "X-Namespace": "activate",
    "Authorization": "Bearer token",
}


def create_upload(client, *, year: int, key: str) -> str:
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,321,09120000000,0011111111,رضا,مرادی\r\n"
    ).encode("utf-8")
    response = client.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": str(year)},
        files={"file": ("file.csv", csv_content, "text/csv")},
        headers={**HEADERS, "Idempotency-Key": key, "X-Request-ID": key},
    )
    return response.json()["id"]


def test_activate_one_per_year_with_lock(uploads_app):
    first = create_upload(uploads_app, year=1400, key="act-1")
    second = create_upload(uploads_app, year=1400, key="act-2")
    ok = uploads_app.post(f"/uploads/{first}/activate", headers=HEADERS)
    assert ok.status_code == 200
    conflict = uploads_app.post(f"/uploads/{second}/activate", headers=HEADERS)
    assert conflict.status_code == 400
    assert conflict.json()["code"] == "UPLOAD_ACTIVATION_CONFLICT"


def test_concurrent_activate_single_winner(service, uploads_app):
    upload_id = create_upload(uploads_app, year=1401, key="act-concurrent")

    def activate_once():
        try:
            return service.activate(upload_id, rid=uuid4().hex, namespace="concurrent")
        except UploadError as exc:
            return exc.envelope.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: activate_once(), range(2)))

    codes = [res if isinstance(res, str) else None for res in results if isinstance(res, str)]
    assert codes.count("UPLOAD_ACTIVATION_CONFLICT") == 1
    assert any(not isinstance(res, str) for res in results)
