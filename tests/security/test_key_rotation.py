from __future__ import annotations

from datetime import datetime, timezone

import pytest

from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.security.config import SigningKeyDefinition
from security.signing import KeyRingSigner, VerificationError, keyring_from_definitions, deterministic_secret


@pytest.fixture()
def signer() -> KeyRingSigner:
    definitions = (
        SigningKeyDefinition("legacy", deterministic_secret("legacy"), "retired"),
        SigningKeyDefinition("active", deterministic_secret("active"), "active"),
    )
    ring = keyring_from_definitions(definitions)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    return KeyRingSigner(ring, clock=clock, default_ttl_seconds=3600)


def test_dual_key_verify_and_rotate(signer: KeyRingSigner) -> None:
    first = signer.issue("/exports/initial.csv")
    assert signer.verify(first) == "/exports/initial.csv"
    signer.rotate(kid="next", secret=deterministic_secret("next"))
    rotated = signer.issue("/exports/initial.csv")
    assert signer.verify(rotated) == "/exports/initial.csv"
    assert signer.verify(first) == "/exports/initial.csv"
    with pytest.raises(VerificationError):
        signer.verify_url("https://example.com/download?signed=invalid&kid=missing&exp=10&sig=bad")

