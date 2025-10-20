from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_pii_validation(
    oidc_provider,
    oidc_http_client,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
):
    async def _run() -> None:
        code = oidc_provider.issue_code(
            {
                "role": "ADMIN",
                "center_scope": "ALL",
                "userinfo": {"email": "user@example.com"},
            }
        )
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
            await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": code},
                headers={"Idempotency-Key": "pii", "X-RateLimit-Key": "demo"},
            )
        assert all("example.com" not in str(event) for event in audit_log.events)

    asyncio.run(_run())
