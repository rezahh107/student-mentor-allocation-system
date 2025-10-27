from __future__ import annotations

from __future__ import annotations

from tests.helpers.jwt_factory import build_jwt
from tests.rbac.test_admin_vs_manager import _auth_header, api_client


def test_ssr_requires_token(api_client: tuple) -> None:
    client, _ = api_client
    response = client.get("/ui/exports")
    assert response.status_code in {401, 403}
    payload = response.json()
    assert "fa_error_envelope" in payload
    assert payload["fa_error_envelope"]["message"].startswith("درخواست نامعتبر")


def test_manager_ui_hides_admin_controls(api_client: tuple) -> None:
    client, creds = api_client
    now = creds["now_ts"]
    manager_token = build_jwt(
        secret=creds["service_secret"],
        subject="mgr-ui",
        role="MANAGER",
        center=55,
        iat=now,
        exp=now + 3600,
    )
    response = client.get("/ui/exports", headers=_auth_header(manager_token))
    assert response.status_code == 200
    html = response.text
    assert "دسترسی فقط برای مرکز" in html
    assert "دانلود خروجی CSV" not in html


def test_admin_ui_shows_controls(api_client: tuple) -> None:
    client, creds = api_client
    now = creds["now_ts"]
    admin_token = build_jwt(
        secret=creds["service_secret"],
        subject="admin-ui",
        role="ADMIN",
        iat=now,
        exp=now + 3600,
    )
    response = client.get("/ui/exports", headers=_auth_header(admin_token))
    assert response.status_code == 200
    html = response.text
    assert "دانلود خروجی CSV" in html
    assert "نقش کاربر" in html

