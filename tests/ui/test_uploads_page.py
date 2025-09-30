from __future__ import annotations
def test_rtl_form_messages_and_preview(uploads_app):
    response = uploads_app.get("/uploads")
    assert response.status_code == 200
    html = response.text
    assert "dir=\"rtl\"" in html
    assert "hx-post=\"/uploads\"" in html
    assert "پیش‌نمایش" in html
