from __future__ import annotations

import asyncio

import pytest

from auth.errors import ProviderError
from auth.saml_adapter import SAMLAdapter
from sma.config.env_schema import SSOConfig


def test_oversized_saml_assertion(
    saml_provider,
    session_store,
    auth_metrics,
    sso_clock,
    audit_log,
):
    async def _run() -> None:
        config = SSOConfig.from_env(saml_provider.env())
        adapter = SAMLAdapter(
            settings=config.saml,
            session_store=session_store,
            metrics=auth_metrics,
            clock=sso_clock.clock,
            audit_sink=audit_log.sink,
            ldap_mapper=None,
        )
        oversized = "<Assertion>" + "A" * (250 * 1024 + 1) + "</Assertion>"
        with pytest.raises(ProviderError) as exc:
            await adapter.authenticate(assertion=oversized, correlation_id="cid", request_id="rid")
        assert "بسیار بزرگ" in exc.value.message_fa

    asyncio.run(_run())
