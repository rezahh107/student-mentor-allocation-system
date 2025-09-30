from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from src.reliability.clock import Clock
from tests.mock.oidc import MockOIDCProvider


def test_mock_oidc_idp_generates_signed_tokens():
    async def _run() -> None:
        clock = Clock(timezone=ZoneInfo("Asia/Tehran"), _now_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
        provider = MockOIDCProvider(clock=clock)
        code = provider.issue_code({"role": "ADMIN", "center_scope": "ALL"}, code="abc")
        async with httpx.AsyncClient(transport=provider.transport, base_url=provider.issuer) as client:
            response = await client.post("/token", data={"code": code})
            jwks = await client.get("/jwks")
        assert response.status_code == 200
        assert "id_token" in response.json()
        assert jwks.json()["keys"][0]["kid"] == "mock-key"

    asyncio.run(_run())
