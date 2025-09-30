from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.reliability.clock import Clock
from tests.mock.saml import MockSAMLProvider


def test_mock_saml_idp_builds_assertion():
    async def _run() -> str:
        clock = Clock(timezone=ZoneInfo("Asia/Tehran"), _now_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
        provider = MockSAMLProvider(clock=clock)
        return provider.build_assertion(role="ADMIN", center_scope="ALL", name_id="user")

    assertion = asyncio.run(_run())
    assert "<NameID>user</NameID>" in assertion
    assert "Audience" in assertion
