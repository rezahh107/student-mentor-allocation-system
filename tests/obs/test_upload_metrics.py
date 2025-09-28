from __future__ import annotations

pytest_plugins = ("tests.uploads.conftest",)
def test_uploads_metrics_exposed_with_token(uploads_app):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,456,09121111111,0012345678,مینا,باقری\r\n"
    ).encode("utf-8")
    uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1400"},
        files={"file": ("metrics.csv", csv_content, "text/csv")},
        headers={
            "Idempotency-Key": "metrics-1",
            "X-Request-ID": "RID-metrics",
            "X-Namespace": "metrics",
            "Authorization": "Bearer token",
        },
    )
    metrics = uploads_app.get("/metrics", params={"token": "secret-token"})
    assert metrics.status_code == 200
    body = metrics.text
    assert "uploads_total" in body
    assert "upload_duration_seconds_bucket" in body
