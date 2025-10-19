from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


def _tehran_zone() -> ZoneInfo:
    return ZoneInfo("Asia/Tehran")


@dataclasses.dataclass
class DeterministicClock:
    """Deterministic clock seeded to Asia/Tehran timezone."""

    current: datetime = dataclasses.field(
        default_factory=lambda: datetime(2024, 1, 1, 0, 0, 0, tzinfo=_tehran_zone())
    )

    def now(self) -> datetime:
        return self.current

    def tick(self, seconds: float = 0, minutes: float = 0) -> datetime:
        delta = timedelta(seconds=seconds, minutes=minutes)
        self.current = self.current + delta
        return self.current

    def freeze(self, moment: Optional[datetime]) -> datetime:
        if moment is None:
            self.current = datetime(2024, 1, 1, 0, 0, 0, tzinfo=_tehran_zone())
        else:
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=_tehran_zone())
            self.current = moment.astimezone(_tehran_zone())
        return self.current
