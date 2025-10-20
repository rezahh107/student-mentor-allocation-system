from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable, Protocol, Union

import sma.core.clock as core_clock


class Clock(Protocol):
    """Protocol describing deterministic clock access."""

    def now(self) -> dt.datetime:
        ...

    def __call__(self) -> dt.datetime:
        ...


@dataclass(frozen=True)
class FixedClock:
    instant: dt.datetime

    def now(self) -> dt.datetime:
        return self.instant

    def __call__(self) -> dt.datetime:
        return self.now()


@dataclass(frozen=True)
class CallableClock:
    """Adapter turning a simple callable into a full-featured Clock."""

    delegate: Callable[[], dt.datetime]

    def now(self) -> dt.datetime:
        value = self.delegate()
        if not isinstance(value, dt.datetime):  # defensive: avoid subtle bugs in tests
            raise TypeError(f"Clock delegate returned non-datetime value: {type(value)!r}")
        return value

    def __call__(self) -> dt.datetime:
        return self.now()


@dataclass
class SystemClock:
    delegate: core_clock.Clock

    def now(self) -> dt.datetime:
        return self.delegate.now()

    def __call__(self) -> dt.datetime:
        return self.now()


def build_system_clock(timezone: str) -> SystemClock:
    return SystemClock(delegate=core_clock.Clock.for_timezone(timezone))


def ensure_clock(
    clock: Union[Clock, Callable[[], dt.datetime], None],
    *,
    timezone: str = "Asia/Tehran",
) -> Clock:
    """Normalize the provided clock into a full-featured Clock instance."""

    if clock is None:
        return build_system_clock(timezone)
    if hasattr(clock, "now") and callable(getattr(clock, "now")):
        return clock  # type: ignore[return-value]
    return CallableClock(delegate=clock)


__all__ = [
    "Clock",
    "FixedClock",
    "SystemClock",
    "CallableClock",
    "build_system_clock",
    "ensure_clock",
]
