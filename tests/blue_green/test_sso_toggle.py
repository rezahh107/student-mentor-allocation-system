from __future__ import annotations

import asyncio

import httpx

from config.env_schema import SSOConfig
from src.security.sso_app import create_sso_app


def test_sessions_survive_toggle(
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
            warm_code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
            warm = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": warm_code},
                headers={"Idempotency-Key": "warm", "X-RateLimit-Key": "demo"},
            )
            assert warm.status_code == 503
            config.blue_green_state = "green"
            ready_code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
            ready = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": ready_code},
                headers={"Idempotency-Key": "ready", "X-RateLimit-Key": "demo"},
            )
            assert ready.status_code == 200
            sid = ready.cookies.get("bridge_session")
            config.blue_green_state = "blue"
            blocked_code = oidc_provider.issue_code({"role": "ADMIN", "center_scope": "ALL"})
            blocked = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": blocked_code},
                headers={"Idempotency-Key": "blocked", "X-RateLimit-Key": "demo"},
            )
            assert blocked.status_code == 503
        session = await session_store.get(sid)
        assert session is not None

    asyncio.run(_run())
