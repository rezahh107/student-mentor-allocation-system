from __future__ import annotations

import asyncio


def test_session_ttl(session_store):
    async def _run():
        session = await session_store.create(
            correlation_id="rid",
            subject="user",
            role="ADMIN",
            center_scope="ALL",
        )
        assert session.ttl_seconds == 900
        assert (session.expires_at - session.issued_at).total_seconds() == 900

    asyncio.run(_run())
