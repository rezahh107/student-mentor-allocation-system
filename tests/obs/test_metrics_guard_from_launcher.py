from __future__ import annotations

from fastapi.testclient import TestClient

from sma.infrastructure.api.routes import create_app


def test_requires_token():
    client = TestClient(create_app())
    response = client.get("/metrics")
    assert response.status_code == 401
    response = client.get("/metrics", headers={"X-Metrics-Token": "metrics-token"})
    assert response.status_code == 200
