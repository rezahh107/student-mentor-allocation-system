"""Time utilities with injected clock support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo


DEFAULT_TZ = ZoneInfo("Asia/Tehran")


TimeFn = Callable[[], float]


@dataclass(frozen=True)
class Clock:
    """Clock wrapper to avoid direct wall-clock usage."""

    time_fn: TimeFn
    monotonic_fn: TimeFn
    timezone: ZoneInfo = DEFAULT_TZ

    def now(self) -> datetime:
        """Return timezone-aware datetime."""
        return datetime.fromtimestamp(self.time_fn(), tz=self.timezone)

    def monotonic_ms(self) -> int:
        """Return monotonic milliseconds for duration tracking."""
        return int(self.monotonic_fn() * 1000)


def default_clock() -> Clock:
    """Create a default clock with real time providers."""
    import time

    return Clock(time_fn=time.time, monotonic_fn=time.perf_counter, timezone=DEFAULT_TZ)
