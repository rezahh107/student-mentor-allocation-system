"""Clock abstractions for outbox processing."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Clock abstraction for deterministic tests."""

    def now(self) -> datetime:
        """Return a timezone-aware wall-clock timestamp."""

    def monotonic(self) -> float:
        """Return a monotonic reference in seconds."""


class SystemClock(Clock):
    """Default implementation backed by stdlib clocks."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()
