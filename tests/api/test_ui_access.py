from __future__ import annotations

import asyncio

import httpx

from sma.infrastructure.api.routes import create_app


def test_ui_get_is_public_and_bypasses_auth(monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "token-test")
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async def _invoke():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/ui")
            head_response = await client.head("/ui")
            post_response = await client.post(
                "/ui",
                headers={"Idempotency-Key": "post-test-123"},
            )
        return response, head_response, post_response

    response, head_response, post_response = asyncio.run(_invoke())

    assert response.status_code == 200, {
        "headers": dict(response.headers),
        "body": response.text[:120],
    }
    chain = response.headers.get("X-Middleware-Chain", "")
    assert chain.split(",") == ["RateLimit", "Idempotency", "Auth"]

    assert head_response.status_code == 200

    assert post_response.status_code == 401
    payload = post_response.json()
    assert payload["fa_error_envelope"]["code"] == "UNAUTHORIZED"
