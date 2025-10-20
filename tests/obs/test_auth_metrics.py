from __future__ import annotations

import asyncio

import httpx
import pytest

from sma.config.env_schema import SSOConfig
from sma.security.sso_app import create_sso_app


def test_auth_metrics_emitted_and_token_guarded(
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
            await client.post(
                "/auth/callback",
                json={"provider": "oidc", "code": code},
                headers={"Idempotency-Key": "metrics", "X-RateLimit-Key": "demo"},
            )
            denied = await client.get("/metrics")
            assert denied.status_code == 401
            allowed = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert allowed.status_code == 200
        assert "auth_ok_total" in allowed.text

    asyncio.run(_run())


def test_retry_and_exhaustion_series_labels(auth_metrics) -> None:
    auth_metrics.retry_attempts_total.labels(adapter="oidc", reason="jwks").inc()
    auth_metrics.retry_attempts_total.labels(adapter="ldap", reason="timeout").inc(2)
    auth_metrics.retry_exhaustion_total.labels(adapter="oidc", reason="jwks").inc()
    auth_metrics.retry_backoff_seconds.labels(adapter="oidc", reason="jwks").observe(0.123)
    auth_metrics.retry_backoff_seconds.labels(adapter="ldap", reason="timeout").observe(0.456)

    registry = auth_metrics.registry
    assert registry.get_sample_value(
        "auth_retry_attempts_total",
        {"adapter": "oidc", "reason": "jwks"},
    ) == 1.0
    assert registry.get_sample_value(
        "auth_retry_attempts_total",
        {"adapter": "ldap", "reason": "timeout"},
    ) == 2.0
    assert registry.get_sample_value(
        "auth_retry_exhaustion_total",
        {"adapter": "oidc", "reason": "jwks"},
    ) == 1.0
    assert registry.get_sample_value(
        "auth_retry_backoff_seconds_sum",
        {"adapter": "ldap", "reason": "timeout"},
    ) == pytest.approx(0.456)
