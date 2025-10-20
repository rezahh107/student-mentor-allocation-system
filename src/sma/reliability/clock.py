from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo

from sma.core.clock import tehran_clock


_DEFAULT_CLOCK = tehran_clock()


def _utc_now() -> _dt.datetime:
    return _DEFAULT_CLOCK.now()


@dataclass(slots=True)
class Clock:
    """Deterministic clock with injectable time source."""

    timezone: ZoneInfo
    _now_factory: Callable[[], _dt.datetime] = _utc_now

    def now(self) -> _dt.datetime:
        """Return an aware datetime using the configured timezone."""

        current = self._now_factory()
        if current.tzinfo is None:
            current = current.replace(tzinfo=_dt.timezone.utc)
        return current.astimezone(self.timezone)

    def isoformat(self) -> str:
        return self.now().isoformat()

    def measure(self, func: Callable[[], object]) -> tuple[object, float]:
        """Execute *func* returning elapsed seconds using the injected clock."""

        start = self.now()
        result = func()
        end = self.now()
        elapsed = (end - start).total_seconds()
        return result, max(0.0, elapsed)


__all__ = ["Clock"]
