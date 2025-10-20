from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider
from sma.phase6_import_to_sabt.clock import FixedClock


def test_signed_url_ttl_is_clock_driven() -> None:
    frozen = datetime(2024, 1, 1, 8, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    signer = HMACSignedURLProvider(secret="secret", clock=FixedClock(frozen))
    signed = signer.sign("/tmp/export.csv", expires_in=900)
    parsed = urlparse(signed)
    exp = parse_qs(parsed.query).get("exp", [None])[0]
    assert exp == str(int(frozen.timestamp()) + 900)
    assert signer.verify(signed, now=frozen + timedelta(seconds=899))
    assert not signer.verify(signed, now=frozen + timedelta(seconds=901))
