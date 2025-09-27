from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Protocol describing deterministic clock access."""

    def now(self) -> dt.datetime:
        ...


@dataclass(frozen=True)
class FixedClock:
    instant: dt.datetime

    def now(self) -> dt.datetime:
        return self.instant


@dataclass
class SystemClock:
    timezone: ZoneInfo

    def now(self) -> dt.datetime:
        return dt.datetime.now(tz=self.timezone)


def build_system_clock(timezone: str) -> SystemClock:
    return SystemClock(timezone=ZoneInfo(timezone))


__all__ = ["Clock", "FixedClock", "SystemClock", "build_system_clock"]
