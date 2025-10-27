"""Clock behaviour must rely on injected timezone rather than wall clock."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sma.ci_hardening.clock import Clock


def test_no_wallclock(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Clock.now`` must delegate to timezone-aware datetime usage."""

    captured: dict[str, datetime] = {}

    class _Recorder:
        @staticmethod
        def now(*, tz: ZoneInfo) -> datetime:
            assert tz.key == "Asia/Tehran"
            result = datetime(2024, 1, 1, 0, 0, 0, tzinfo=tz)
            captured["value"] = result
            return result

    monkeypatch.setattr("sma.ci_hardening.clock.datetime", _Recorder)
    clock = Clock(tz=ZoneInfo("Asia/Tehran"))
    now = clock.now()
    assert now == captured["value"]
