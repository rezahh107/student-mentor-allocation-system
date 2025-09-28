from __future__ import annotations

pytest_plugins = ("tests.uploads.conftest",)
def test_rate_then_idem_then_auth(uploads_app):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,111,09120000000,0012345678,علی,موسوی\r\n"
    ).encode("utf-8")
    response = uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1402"},
        files={"file": ("file.csv", csv_content, "text/csv")},
        headers={
            "Idempotency-Key": "mw-1",
            "X-Request-ID": "RID-mw",
            "X-Namespace": "mw",
            "Authorization": "Bearer token",
            "X-Debug-Middleware": "1",
        },
    )
    assert response.status_code == 200
    assert response.json()["middleware_chain"] == ["rate", "idem", "auth"]
