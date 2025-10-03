import pytest

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_metrics_requires_token(client, clean_state):
    client.app.state.middleware_state.metrics_token = "TESTTOKEN1234567890"
    client.app.state.middleware_state.metrics_ip_allowlist = {"127.0.0.1"}

    unauthorized = await client.get("/metrics")
    assert unauthorized.status_code == 401
    body = unauthorized.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"
    assert body["error"]["message_fa"] == "دسترسی غیرمجاز؛ احراز هویت لازم است."

    authorized = await client.get(
        "/metrics",
        headers={"Authorization": "Bearer TESTTOKEN1234567890"},
    )
    assert authorized.status_code == 200
    assert "http_requests_total" in authorized.text
