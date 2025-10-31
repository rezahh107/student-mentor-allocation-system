from __future__ import annotations

from http import HTTPStatus

from fastapi import Request
from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.config import AppConfig, AuthConfig


def test_post_pipeline_preserves_rate_idempotency_auth_order() -> None:
    """Ensure POST requests traverse RateLimit → Idempotency → Auth in that order."""

    config = AppConfig(auth=AuthConfig(allow_all=True))
    app = create_application(config=config)

    @app.post("/__echo")
    async def echo(request: Request) -> dict[str, object]:
        chain = getattr(request.state, "middleware_chain", [])
        return {"status": "ok", "chain": chain}

    with TestClient(app) as client:
        response = client.post("/__echo", headers={"Idempotency-Key": "echo-1"})

    assert response.status_code == HTTPStatus.OK

    chain = response.json()["chain"]
    assert chain[:3] == ["RateLimit", "Idempotency", "Auth"], chain

    header_chain = response.headers.get("X-Middleware-Chain", "")
    assert header_chain.startswith("RateLimit,Idempotency,Auth"), header_chain
