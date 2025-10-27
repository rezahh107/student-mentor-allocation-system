"""Timezone availability checks for deterministic execution."""

from __future__ import annotations

from zoneinfo import ZoneInfoNotFoundError

import pytest

from sma.ci_hardening.runtime import (
    RuntimeConfigurationError,
    ensure_tehran_tz,
)


def test_tehran_zone_available() -> None:
    """Ensure Asia/Tehran can be resolved from tzdata."""

    zone = ensure_tehran_tz()
    assert zone.key == "Asia/Tehran"


def test_tehran_zone_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing timezone data must raise a deterministic Persian error."""

    def _raise(_: str) -> None:
        raise ZoneInfoNotFoundError()

    monkeypatch.setattr("sma.ci_hardening.runtime.ZoneInfo", _raise)
    with pytest.raises(RuntimeConfigurationError) as exc:
        ensure_tehran_tz()
    assert "منطقهٔ زمانی" in str(exc.value)
