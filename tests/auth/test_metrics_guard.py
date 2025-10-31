import pytest

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_metrics_endpoint_is_public(client, clean_state):
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
