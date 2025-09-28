from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


BAKU_TZ = ZoneInfo("Asia/Baku")


class Clock(Protocol):
    def now(self) -> datetime:
        ...


@dataclass(slots=True)
class SystemClock:
    tz: ZoneInfo = BAKU_TZ

    def now(self) -> datetime:
        return datetime.now(tz=self.tz).astimezone(self.tz)


@dataclass(slots=True)
class FrozenClock:
    fixed: datetime

    def now(self) -> datetime:
        return self.fixed.astimezone(BAKU_TZ)
