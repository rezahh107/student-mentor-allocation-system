from __future__ import annotations

from sma.phase6_import_to_sabt.security.rbac import AuthenticatedActor


def test_existing_rbac():
    actor = AuthenticatedActor(token_fingerprint="abc", role="ADMIN", center_scope=None, metrics_only=False)
    assert actor.can_access_center(101)
