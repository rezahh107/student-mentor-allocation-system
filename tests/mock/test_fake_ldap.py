from __future__ import annotations

import asyncio

from tests.mock.fake_ldap import FakeLDAPDirectory


def test_fake_ldap_returns_groups():
    directory = FakeLDAPDirectory({"alice": ["ADMIN:ALL", "extra"]})

    async def _run():
        return await directory.fetch_groups("alice")

    groups = asyncio.run(_run())
    assert groups == ["ADMIN:ALL", "extra"]
