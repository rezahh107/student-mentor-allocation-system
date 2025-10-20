from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_middleware_order_post_callback(
    oidc_provider,
    oidc_http_client,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
):
    async def _run() -> None:
        code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
        config = SSOConfig.from_env(oidc_provider.env())
        app = create_sso_app(
            config=config,
            clock=sso_clock.clock,
            session_store=session_store,
            metrics=auth_metrics,
            audit_sink=audit_log.sink,
            http_client=oidc_http_client,
            ldap_mapper=None,
            metrics_token="metrics-token",
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": code},
                headers={"Idempotency-Key": "order-key", "X-RateLimit-Key": "demo"},
            )
        assert response.status_code == 200
        assert response.headers["X-Middleware-Order"] == "RateLimit,Idempotency,Auth"

    asyncio.run(_run())
