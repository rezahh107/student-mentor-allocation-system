from __future__ import annotations

"""Deterministic clock utilities bound to the Asia/Tehran timezone.

The helpers in this module intentionally avoid reading from the system clock.
Tests and runtime code inject :class:`Clock` instances to make all temporal
behaviour reproducible.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

ASIA_TEHRAN = ZoneInfo("Asia/Tehran")


@dataclass
class Clock:
    """A simple controllable clock.

    The clock stores both a wall time (timezone-aware) and a monotonic counter
    expressed in seconds. Advancing the clock updates both values. The default
    epoch matches ``2024-01-01T00:00:00+03:30`` to keep assertions predictable.
    """

    _now: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1, tzinfo=ASIA_TEHRAN)
    )
    _monotonic: float = 0.0

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return self._now

    def monotonic(self) -> float:
        """Return the deterministic monotonic counter in seconds."""

        return self._monotonic

    def advance(self, seconds: float) -> None:
        """Advance both wall and monotonic clocks by ``seconds``."""

        delta = timedelta(seconds=seconds)
        self._now = (self._now + delta).astimezone(ASIA_TEHRAN)
        self._monotonic += seconds

    def freeze(self, moment: datetime) -> None:
        """Freeze the clock to ``moment`` (converted to Asia/Tehran tz)."""

        self._now = moment.astimezone(ASIA_TEHRAN)

    def iter_ticks(self, step: float) -> Iterator[datetime]:
        """Generate a deterministic sequence of timestamps with ``step`` seconds."""

        while True:
            yield self.now()
            self.advance(step)

    def sleep(self, seconds: float) -> None:
        """Virtual sleep implemented via :meth:`advance`."""

        self.advance(seconds)


class ClockProvider:
    """Provides dedicated :class:`Clock` instances for concurrent workers."""

    def __init__(self, factory: Callable[[], Clock] | None = None) -> None:
        self._factory = factory or Clock

    def new(self) -> Clock:
        """Return a fresh clock instance."""

        return self._factory()


def tehran_midnight(year: int, month: int, day: int) -> datetime:
    """Helper used in tests to create midnight timestamps in Tehran."""

    return datetime(year, month, day, tzinfo=ASIA_TEHRAN)
