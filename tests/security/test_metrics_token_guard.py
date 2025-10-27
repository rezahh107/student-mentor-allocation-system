from __future__ import annotations

from tests.rbac.test_admin_vs_manager import api_client


def test_metrics_requires_bearer_token(api_client: tuple) -> None:
    client, creds = api_client
    response = client.get("/metrics")
    assert response.status_code == 403
    payload = response.json()
    assert payload["fa_error_envelope"]["message"] == "دسترسی به /metrics نیازمند توکن فقط‌خواندنی است."

    auth_headers = {"Authorization": f"Bearer {creds['metrics_token']}"}
    ok_response = client.get("/metrics", headers=auth_headers)
    assert ok_response.status_code == 200
    assert ok_response.text.startswith("# HELP")

