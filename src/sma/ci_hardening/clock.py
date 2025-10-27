"""Deterministic clock abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Clock:
    """Clock that yields timezone-aware datetimes."""

    tz: ZoneInfo

    def now(self) -> datetime:
        """Return the current time in the configured timezone."""

        return datetime.now(tz=self.tz)


__all__ = ["Clock"]
