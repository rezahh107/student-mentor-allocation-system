from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_zero_downtime(
    oidc_provider,
    oidc_http_client,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
):
    async def _run() -> None:
        env = oidc_provider.env()
        env["SSO_BLUE_GREEN_STATE"] = "warming"
        config = SSOConfig.from_env(env)
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
            login = await client.get("/auth/login")
            assert login.status_code == 200
            config.blue_green_state = "green"
            code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
            ready = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": code},
                headers={"Idempotency-Key": "zero", "X-RateLimit-Key": "demo"},
            )
            assert ready.status_code == 200

    asyncio.run(_run())
