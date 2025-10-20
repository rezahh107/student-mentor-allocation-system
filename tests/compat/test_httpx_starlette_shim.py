from __future__ import annotations

from fastapi import FastAPI

from sma.phase6_import_to_sabt.compat import TestClient, create_test_client


def test_testclient_basic_flow():
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"pong": "ok"}

    client = TestClient(app)
    try:
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"pong": "ok"}
    finally:
        client.close()


def test_context_manager_helper():
    app = FastAPI()

    @app.post("/echo")
    def echo(payload: dict[str, str]) -> dict[str, str]:
        return payload

    with create_test_client(app) as client:
        response = client.post("/echo", json={"value": "سلام"})
        assert response.status_code == 200
        assert response.json() == {"value": "سلام"}
