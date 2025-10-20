from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_audit_events_no_pii_and_tehran_clock(
    oidc_provider,
    oidc_http_client,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
) -> None:
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
            await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": code},
                headers={"Idempotency-Key": "audit-ok", "X-RateLimit-Key": "demo"},
            )
            failure = await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": "invalid"},
                headers={"Idempotency-Key": "audit-fail", "X-RateLimit-Key": "demo"},
            )
        assert failure.status_code == 502
        assert any(event["action"] == "AUTHN_FAIL" for event in audit_log.events)
        for event in audit_log.events:
            assert "AUTHN_" in event["action"]
            assert event["ts"].endswith("+03:30")
            assert len(event.get("cid", "")) == 24

    asyncio.run(_run())
