from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Protocol

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 safeguard
    from backports.zoneinfo import ZoneInfo  # type: ignore


class Clock(Protocol):
    """Simple protocol representing deterministic clock sources."""

    def now(self) -> _dt.datetime:
        """Return the current timestamp in Asia/Tehran timezone."""


@dataclass(slots=True)
class FrozenClock:
    """Clock returning a pre-defined timestamp (deterministic)."""

    instant: _dt.datetime

    def now(self) -> _dt.datetime:
        return self.instant


def tehran_clock(base: _dt.datetime | None = None) -> FrozenClock:
    """Create a frozen clock pinned to Asia/Tehran.

    Parameters
    ----------
    base:
        Optional naive/aware datetime.  If omitted a deterministic default is
        used ensuring reproducibility during CI and unit tests.
    """

    tz = ZoneInfo("Asia/Tehran")
    if base is None:
        base = _dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=tz)
    elif base.tzinfo is None:
        base = base.replace(tzinfo=tz)
    else:
        base = base.astimezone(tz)
    return FrozenClock(base)
