from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sma.core import clock


@pytest.mark.evidence("AGENTS.md::Determinism")
@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_tehran_timezone_fallback_when_tzdata_missing(monkeypatch) -> None:
    original_zoneinfo = clock.ZoneInfo

    def missing_zoneinfo(name: str) -> clock.ZoneInfo:  # type: ignore[override]
        raise clock.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(clock, "ZoneInfo", missing_zoneinfo)
    resolution = clock.try_zoneinfo("Asia/Tehran")
    assert resolution.tzdata_missing is True
    aware = datetime(2024, 1, 1, tzinfo=resolution.tzinfo)
    assert aware.utcoffset() == timedelta(hours=3, minutes=30)
    deterministic = clock.DeterministicClock(
        timezone=resolution.tzinfo,
        now_factory=lambda: datetime(2024, 5, 1, 4, 0, tzinfo=UTC),
    )
    assert deterministic.isoformat() == "2024-05-01T07:30:00+03:30"
    with pytest.raises(ValueError) as excinfo:
        clock.validate_timezone("Asia/Tehran", require_iana=True)
    assert str(excinfo.value) == clock.PERSIAN_TZDATA_MISSING
    # Ensure original ZoneInfo restored for downstream imports
    monkeypatch.setattr(clock, "ZoneInfo", original_zoneinfo)


@pytest.mark.evidence("AGENTS.md::Determinism")
def test_tehran_timezone_uses_iana_when_available() -> None:
    resolution = clock.try_zoneinfo("Asia/Tehran")
    assert resolution.tzdata_missing is False
    tzinfo = resolution.tzinfo
    expected_key = getattr(tzinfo, "key", clock.DEFAULT_TIMEZONE)
    assert expected_key == clock.DEFAULT_TIMEZONE
