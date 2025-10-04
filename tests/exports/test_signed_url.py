from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from phase6_import_to_sabt.api import HMACSignedURLProvider
from phase6_import_to_sabt.clock import FixedClock


def test_signed_url_expiry_uses_injected_clock() -> None:
    frozen = datetime(2024, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    provider = HMACSignedURLProvider(secret="secret", clock=FixedClock(frozen))
    signed = provider.sign("/tmp/sample.csv", expires_in=900)
    query = parse_qs(urlparse(signed).query)
    assert query["exp"][0] == str(int(frozen.timestamp()) + 900)
