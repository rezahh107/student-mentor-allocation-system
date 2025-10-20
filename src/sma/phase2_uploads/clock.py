from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from sma.core.clock import Clock as CoreClock, tehran_clock

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


class Clock(Protocol):
    def now(self) -> datetime:
        ...


@dataclass(slots=True)
class SystemClock:
    tz: ZoneInfo = TEHRAN_TZ
    _delegate: CoreClock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._delegate = CoreClock(self.tz)

    def now(self) -> datetime:
        return self._delegate.now()


@dataclass(slots=True)
class FrozenClock:
    fixed: datetime

    def now(self) -> datetime:
        return self.fixed.astimezone(TEHRAN_TZ)


# Backwards compatibility export for existing imports expecting ``BAKU_TZ``.
BAKU_TZ = TEHRAN_TZ


def tehran_system_clock() -> SystemClock:
    """Factory returning a system clock bound to Tehran timezone."""

    return SystemClock(tehran_clock().timezone)
