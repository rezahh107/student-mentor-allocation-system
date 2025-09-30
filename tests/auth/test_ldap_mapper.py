from __future__ import annotations

import asyncio

from auth.ldap_adapter import LdapGroupMapper, LdapSettings
from tests.mock.fake_ldap import FakeLDAPDirectory


def test_ldap_group_to_role_center() -> None:
    directory = FakeLDAPDirectory({"user": ["MANAGER:۰۰۱۲"]})
    mapper = LdapGroupMapper(directory.fetch_groups, settings=LdapSettings(group_rules={}))

    async def _run() -> tuple[str, str]:
        return await mapper({"sub": "user"})

    role, scope = asyncio.run(_run())
    assert role == "MANAGER"
    assert scope == "0012"


def test_ldap_group_rules_override() -> None:
    directory = FakeLDAPDirectory({"user": ["ignored"]})
    settings = LdapSettings(group_rules={"ignored": ("ADMIN", "ALL")})
    mapper = LdapGroupMapper(directory.fetch_groups, settings=settings)

    async def _run() -> tuple[str, str]:
        return await mapper({"sub": "user"})

    role, scope = asyncio.run(_run())
    assert role == "ADMIN"
    assert scope == "ALL"
