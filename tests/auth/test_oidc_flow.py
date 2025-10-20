from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_oidc_ok_maps_to_admin_all(
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
                headers={"Idempotency-Key": "demo-key", "X-RateLimit-Key": "demo"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok", "role": "ADMIN", "center_scope": "ALL"}
        assert "RateLimit" in response.headers["X-Middleware-Order"]
        sid = response.cookies.get("bridge_session")
        session = await session_store.get(sid)
        assert session is not None
        assert session.role == "ADMIN"
        assert session.center_scope == "ALL"
        assert audit_log.events[-1]["action"] == "AUTHN_OK"
        metrics = auth_metrics.ok_total.labels(provider="oidc")._value.get()
        assert metrics == 1.0

    asyncio.run(_run())
