"""Unified deterministic clock abstraction for the whole application.

This module is the only place where direct access to the system wall clock is
permitted. All other modules must inject an instance of :class:`Clock` or use a
testing double such as :class:`FrozenClock`.

The default timezone is ``Asia/Tehran`` but the implementation supports any
IANA timezone identifier that can be resolved by :mod:`zoneinfo`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol
from zoneinfo import ZoneInfo


class SupportsNow(Protocol):
    """Protocol implemented by objects that expose a ``now`` method."""

    def now(self) -> datetime:
        """Return the current timezone-aware datetime."""


def _system_now() -> datetime:
    """Return an aware UTC datetime using the system clock."""

    return datetime.now(UTC)


@dataclass(slots=True)
class Clock:
    """Deterministic clock facade with dependency-injected time source."""

    timezone: ZoneInfo
    _now_factory: Callable[[], datetime] = _system_now

    def now(self) -> datetime:
        """Return the current datetime in the configured timezone."""

        current = self._now_factory()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current.astimezone(self.timezone)

    def isoformat(self) -> str:
        """Return an ISO formatted string of :meth:`now`."""

        return self.now().isoformat()

    @classmethod
    def for_timezone(cls, tz_name: str, now_factory: Callable[[], datetime] | None = None) -> "Clock":
        """Create a clock for the given IANA timezone name."""

        return cls(validate_timezone(tz_name), now_factory or _system_now)


@dataclass(slots=True)
class FrozenClock:
    """Clock implementation that always returns the frozen value."""

    timezone: ZoneInfo
    _current: datetime | None = None

    def now(self) -> datetime:
        if self._current is None:
            raise RuntimeError("Frozen clock not initialised; call set() first")
        return self._current

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("Frozen clock values must be timezone-aware")
        self._current = value.astimezone(self.timezone)

    def tick(self, delta_seconds: float) -> None:
        if self._current is None:
            raise RuntimeError("Cannot tick before initializing frozen clock")
        self._current = self._current + timedelta(seconds=delta_seconds)


def validate_timezone(tz_name: str) -> ZoneInfo:
    """Validate and return a :class:`ZoneInfo` instance for *tz_name*."""

    try:
        return ZoneInfo(tz_name)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise ValueError(
            "CONFIG_TZ_INVALID: «مقدار TIMEZONE نامعتبر است؛ لطفاً یک ناحیهٔ زمانی IANA معتبر وارد کنید.»"
        ) from exc


DEFAULT_TIMEZONE = "Asia/Tehran"


def tehran_clock(now_factory: Callable[[], datetime] | None = None) -> Clock:
    """Return a clock bound to the Tehran timezone."""

    return Clock.for_timezone(DEFAULT_TIMEZONE, now_factory=now_factory)


__all__ = [
    "Clock",
    "FrozenClock",
    "SupportsNow",
    "DEFAULT_TIMEZONE",
    "tehran_clock",
    "validate_timezone",
]

