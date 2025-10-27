from __future__ import annotations

from datetime import datetime, timezone

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.obs.metrics import build_metrics
from sma.phase6_import_to_sabt.security.signer import DualKeySigner, SigningKeyDefinition, SigningKeySet


def test_dual_key_signer_accepts_retired_key_for_verification() -> None:
    metrics = build_metrics("rotation_test")
    clock = FixedClock(instant=datetime(2024, 1, 1, tzinfo=timezone.utc))
    initial_keys = SigningKeySet(
        [
            SigningKeyDefinition("active", "secret-active", "active"),
            SigningKeyDefinition("next", "secret-next", "next"),
        ]
    )
    signer = DualKeySigner(keys=initial_keys, clock=clock, metrics=metrics, default_ttl_seconds=300)
    components = signer.issue("exports/file.csv", ttl_seconds=120)

    # Rotation: promote "next" to active and retire previous key.
    rotated_keys = SigningKeySet(
        [
            SigningKeyDefinition("active", "secret-active", "retired"),
            SigningKeyDefinition("next", "secret-next", "active"),
        ]
    )
    rotated = DualKeySigner(keys=rotated_keys, clock=clock, metrics=metrics, default_ttl_seconds=300)

    path = rotated.verify_components(
        token_id=components.token_id,
        kid=components.kid,
        expires=components.expires,
        signature=components.signature,
        now=clock.now(),
    )
    assert path == "exports/file.csv"

