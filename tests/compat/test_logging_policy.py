from __future__ import annotations

import asyncio
import logging

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_logging_policy(caplog, oidc_provider, oidc_http_client, session_store, auth_metrics, sso_clock, audit_log):
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
            with caplog.at_level(logging.INFO):
                await client.post(
                    "/auth/callback",
                    json={"provider": "oidc", "code": code},
                    headers={
                        "Idempotency-Key": "log",
                        "X-RateLimit-Key": "demo",
                        "X-Request-ID": "RID1234567890",
                    },
                )
        records = [record for record in caplog.records if record.getMessage() == "OIDC_AUTH_OK"]
        assert records
        assert len(records[0].cid) == 8

    asyncio.run(_run())
