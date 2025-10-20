from __future__ import annotations

import asyncio

import httpx

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_saml_ok_maps_manager_center(
    saml_provider,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
):
    async def _run() -> None:
        assertion = saml_provider.build_assertion(role="MANAGER", center_scope="۰۱۲۳")
        config = SSOConfig.from_env(saml_provider.env())
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport, base_url="https://unused.local") as http_client:
            app = create_sso_app(
                config=config,
                clock=sso_clock.clock,
                session_store=session_store,
                metrics=auth_metrics,
                audit_sink=audit_log.sink,
                http_client=http_client,
                ldap_mapper=None,
                metrics_token="metrics-token",
            )
            transport_app = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport_app, base_url="http://testserver") as client:
                response = await client.post(
                    "/auth/callback",
                    json={"provider": "saml", "assertion": assertion},
                    headers={"Idempotency-Key": "saml-key", "X-RateLimit-Key": "demo"},
                )
        assert response.status_code == 200
        payload = response.json()
        assert payload == {"status": "ok", "role": "MANAGER", "center_scope": "0123"}
        sid = response.cookies.get("bridge_session")
        session = await session_store.get(sid)
        assert session.center_scope == "0123"
        assert audit_log.events[-1]["action"] == "AUTHN_OK"
        saml_metric = auth_metrics.ok_total.labels(provider="saml")._value.get()
        assert saml_metric == 1.0

    asyncio.run(_run())
