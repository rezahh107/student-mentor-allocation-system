from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_ui_pages_are_rtl(async_client):
    for path in ("/ui/health", "/ui/exports", "/ui/jobs/1", "/ui/uploads"):
        resp = await async_client.get(path)
        assert resp.status_code == 200
        assert 'lang="fa-IR"' in resp.text
        assert 'dir="rtl"' in resp.text
