from __future__ import annotations
def test_freeze_clock_baku_applied_to_manifest(uploads_app, clock):
    csv_content = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
        "1,500,09123333333,0099999999,سارا,جلالی\r\n"
    ).encode("utf-8")
    response = uploads_app.post(
        "/uploads",
        data={"profile": "ROSTER_V1", "year": "1400"},
        files={"file": ("clock.csv", csv_content, "text/csv")},
        headers={
            "Idempotency-Key": "clock-1",
            "X-Request-ID": "RID-clock",
            "X-Namespace": "clock",
            "Authorization": "Bearer token",
        },
    )
    manifest = response.json()["manifest"]
    assert manifest["generated_at"] == clock.now().isoformat()
