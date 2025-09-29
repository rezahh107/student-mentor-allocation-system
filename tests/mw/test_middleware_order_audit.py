from __future__ import annotations

import httpx
import pytest

from src.audit.api import create_audit_api


@pytest.mark.asyncio
async def test_order_ratelimit_idem_auth_applies(audit_env):
    app = create_audit_api(
        service=audit_env.service,
        exporter=audit_env.exporter,
        secret_key="audit-secret",
        metrics_token="metrics-token",
        rate_limit_per_minute=10,
        rate_limit_window_seconds=60,
        idempotency_ttl_seconds=60,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/audit",
            headers={
                "X-Role": "ADMIN",
                "X-Correlation-ID": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            },
        )
    assert response.status_code == 200, audit_env.debug_context()
    assert response.headers.get("X-Middleware-Order") == "RateLimit,Idempotency,Auth", audit_env.debug_context()
