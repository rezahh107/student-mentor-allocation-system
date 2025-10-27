from __future__ import annotations

import time

from tests.rbac.test_admin_vs_manager import api_client


def _measure(client, path: str) -> float:
    start = time.perf_counter()
    response = client.get(path)
    elapsed = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, response.text
    return elapsed


def test_health_endpoints_under_budget(api_client: tuple) -> None:
    client, _ = api_client
    health = _measure(client, "/healthz")
    ready = _measure(client, "/readyz")
    assert health < 200
    assert ready < 200

