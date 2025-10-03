import uuid

import pytest

from tests.hardened_api.conftest import setup_test_data
from src.hardened_api.middleware_chain import POST_CHAIN

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_middleware_order_post_exact(client, clean_state):
    suffix = f"{uuid.uuid4().int % 1_000_000:06d}"
    payload = setup_test_data(suffix)
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Idempotency-Key": f"idem-test-{uuid.uuid4().hex[:12]}",
        "X-Debug-MW-Probe": "trace",
        "Content-Type": "application/json; charset=utf-8",
    }

    response = await client.post("/allocations", json=payload, headers=headers)

    assert response.status_code == 200, response.text
    correlation_id = response.headers["X-Correlation-ID"]
    assert response.headers["X-MW-Trace"] == f"{correlation_id}|RateLimit>Idempotency>Auth"
    assert tuple(client.app.state.middleware_post_chain) == POST_CHAIN
