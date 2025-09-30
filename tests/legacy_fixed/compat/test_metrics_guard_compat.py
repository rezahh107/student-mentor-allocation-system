from __future__ import annotations

import asyncio

import httpx

from config.env_schema import SSOConfig
from src.security.sso_app import create_sso_app


def test_metrics_guard(oidc_provider, oidc_http_client, session_store, auth_metrics, sso_clock, audit_log):
    async def _run() -> None:
        config = SSOConfig.from_env(oidc_provider.env())
        token = "metrics-token"
        app = create_sso_app(
            config=config,
            clock=sso_clock.clock,
            session_store=session_store,
            metrics=auth_metrics,
            audit_sink=audit_log.sink,
            http_client=oidc_http_client,
            ldap_mapper=None,
            metrics_token=token,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthorized = await client.get("/metrics")
            assert unauthorized.status_code == 401
            authorized = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert authorized.status_code == 200

    asyncio.run(_run())
