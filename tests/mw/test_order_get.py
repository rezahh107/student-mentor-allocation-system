import pytest

from src.hardened_api.middleware_chain import GET_CHAIN

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_middleware_order_get_paths(client, clean_state):
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "X-Debug-MW-Probe": "trace",
    }

    response = await client.get("/status", headers=headers)

    assert response.status_code == 200, response.text
    correlation_id = response.headers["X-Correlation-ID"]
    assert response.headers["X-MW-Trace"] == f"{correlation_id}|RateLimit>Auth"
    assert tuple(client.app.state.middleware_get_chain) == GET_CHAIN
