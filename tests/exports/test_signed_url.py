from datetime import datetime, timedelta, timezone

from src.phase6_import_to_sabt.api import DualKeyHMACSignedURLProvider


def test_signed_url_accept_reject_kid_and_ttl():
    now = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def clock() -> datetime:
        return now

    signer = DualKeyHMACSignedURLProvider(
        active=("active", "secret-a"),
        next_=("next", "secret-b"),
        base_url="https://files.local/export",
        clock=clock,
    )

    signed_active = signer.sign("/tmp/export.csv", expires_in=600)

    assert signer.verify(signed_active, now=now + timedelta(seconds=10))
    assert not signer.verify(signed_active, now=now + timedelta(seconds=601))

    signer.rotate(active=("next", "secret-b"), next_=("future", "secret-c"))
    signed_next = signer.sign("/tmp/export.csv", expires_in=600)

    assert signer.verify(signed_next, now=now + timedelta(seconds=20))

    tampered = signed_active.replace("kid=active", "kid=unknown")
    assert not signer.verify(tampered, now=now + timedelta(seconds=20))
