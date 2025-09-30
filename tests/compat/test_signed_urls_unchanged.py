from __future__ import annotations

from src.phase6_import_to_sabt.security import enforce_center_scope, AuthenticatedActor


def test_signed_urls_unchanged():
    actor = AuthenticatedActor(token_fingerprint="x", role="ADMIN", center_scope=None, metrics_only=False)
    enforce_center_scope(actor, center=42)
