"""Clock abstractions for outbox processing."""
from __future__ import annotations

import time
from typing import Protocol

from sma.core.clock import Clock as AppClock, tehran_clock


class Clock(Protocol):
    """Clock abstraction for deterministic tests."""

    def now(self):  # pragma: no cover - protocol
        ...

    def monotonic(self) -> float:  # pragma: no cover - protocol
        ...


class SystemClock(Clock):
    """Default implementation backed by stdlib clocks."""

    def __init__(self, *, clock: AppClock | None = None) -> None:
        self._clock = clock or tehran_clock()

    def now(self):
        return self._clock.now()

    def monotonic(self) -> float:
        return time.monotonic()
