from __future__ import annotations

pytest_plugins = ("tests.uploads.conftest",)


def test_rate_then_idem_then_auth(cleanup_fixtures, uploads_app):
    cleanup_fixtures.flush_state()
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
            "X-Namespace": cleanup_fixtures.namespace,
            "Authorization": "Bearer token",
            "X-Debug-Middleware": "1",
        },
    )
    assert response.status_code == 200, cleanup_fixtures.context(status=response.status_code)
    payload = response.json()
    assert payload["middleware_chain"] == ["rate", "idem", "auth"], cleanup_fixtures.context(payload=payload)
