"""Deterministic clock abstractions centred around ``Asia/Tehran``.

This module is the single entry-point for interacting with wall clock time.
All runtime code must depend on :class:`Clock` (or one of its implementations)
instead of calling ``datetime.now`` or ``time.time`` directly. Tests should use
:class:`FrozenClock` for deterministic behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import unicodedata
from typing import Callable, Protocol, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Tehran"
_MAX_TZ_LENGTH = 255
T = TypeVar("T")

_PERSIAN_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
_ZERO_WIDTH_CHARS = ("\u200c", "\u200d", "\ufeff")


def _system_now() -> datetime:
    """Return an aware UTC datetime using the system wall clock."""

    return datetime.now(UTC)


class SupportsNow(Protocol):
    """Protocol implemented by objects exposing a ``now`` method."""

    def now(self) -> datetime:  # pragma: no cover - structural typing
        ...


def _coerce_aware(value: datetime, *, timezone: ZoneInfo) -> datetime:
    """Ensure *value* is timezone-aware and normalised to *timezone*."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(timezone)


def _normalise_timezone_name(tz_name: str | None) -> str:
    if tz_name is None:
        raise ValueError("CONFIG_TZ_INVALID: «مقدار ناحیهٔ زمانی خالی است.»")

    candidate = unicodedata.normalize("NFKC", str(tz_name))
    candidate = candidate.translate(_PERSIAN_DIGIT_MAP).translate(_ARABIC_DIGIT_MAP)
    for char in _ZERO_WIDTH_CHARS:
        candidate = candidate.replace(char, "")
    candidate = candidate.strip()
    if not candidate:
        raise ValueError("CONFIG_TZ_INVALID: «مقدار ناحیهٔ زمانی خالی است.»")
    if len(candidate) > _MAX_TZ_LENGTH:
        raise ValueError("CONFIG_TZ_INVALID: «طول ناحیهٔ زمانی بیش از حد مجاز است.»")
    parts = [part.capitalize() for part in candidate.split("/") if part]
    canonical = "/".join(parts)
    return canonical or candidate


def validate_timezone(tz_name: str) -> ZoneInfo:
    """Validate *tz_name* and return an instantiated :class:`ZoneInfo`."""

    canonical = _normalise_timezone_name(tz_name)
    if canonical != DEFAULT_TIMEZONE:
        raise ValueError(
            f"CONFIG_TZ_INVALID: «منطقهٔ زمانی مجاز فقط Asia/Tehran است؛ مقدار یافت‌شده: {canonical}»"
        )
    try:
        return ZoneInfo(canonical)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - defensive
        raise ValueError(
            f"CONFIG_TZ_INVALID: «منطقهٔ زمانی مجاز فقط Asia/Tehran است؛ مقدار یافت‌شده: {canonical}»"
        ) from exc


class Clock(ABC):
    """Abstract deterministic clock interface."""

    timezone: ZoneInfo

    @abstractmethod
    def now(self) -> datetime:
        """Return the current datetime in :attr:`timezone`."""

    def isoformat(self) -> str:
        """Return :meth:`now` formatted as ISO 8601."""

        return self.now().isoformat()

    def unix_timestamp(self) -> float:
        """Return the epoch seconds corresponding to :meth:`now`."""

        return self.now().timestamp()

    @classmethod
    def for_timezone(
        cls, tz_name: str, *, now_factory: Callable[[], datetime] | None = None
    ) -> "SystemClock":
        """Instantiate a :class:`SystemClock` for *tz_name*."""

        return SystemClock(timezone=validate_timezone(tz_name), now_factory=now_factory or _system_now)

    @classmethod
    def for_tehran(cls, *, now_factory: Callable[[], datetime] | None = None) -> "SystemClock":
        """Return a :class:`SystemClock` configured for ``Asia/Tehran``."""

        return cls.for_timezone(DEFAULT_TIMEZONE, now_factory=now_factory)


@dataclass(slots=True)
class SystemClock(Clock):
    """Clock backed by the process wall clock."""

    timezone: ZoneInfo
    now_factory: Callable[[], datetime] = field(default=_system_now, repr=False)

    def now(self) -> datetime:  # pragma: no branch - simple call
        return _coerce_aware(self.now_factory(), timezone=self.timezone)


@dataclass(slots=True)
class FrozenClock(Clock):
    """Clock returning a pre-defined deterministic instant."""

    timezone: ZoneInfo
    _current: datetime | None = field(default=None, repr=False)

    def now(self) -> datetime:
        if self._current is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Frozen clock not initialised; call set() first")
        return _coerce_aware(self._current, timezone=self.timezone)

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("CONFIG_CLOCK_FROZEN: «مقدار ورودی باید دارای ناحیهٔ زمانی باشد.»")
        self._current = value

    def tick(self, seconds: float) -> None:
        if self._current is None:
            raise RuntimeError("Frozen clock not initialised; call set() first")
        self._current = self._current + timedelta(seconds=seconds)


def ensure_clock(
    candidate: Clock | SupportsNow | Callable[[], datetime] | None,
    *,
    default: Clock | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> Clock:
    """Normalise *candidate* into a :class:`Clock` instance.

    ``None`` resolves to *default* or a Tehran :class:`SystemClock`. A callable
    will be wrapped so that returned values are coerced to the configured
    timezone.
    """

    if candidate is None:
        return default or Clock.for_timezone(timezone)

    if isinstance(candidate, Clock):
        return candidate

    if isinstance(candidate, SupportsNow):
        return CallableClock(candidate.now, timezone=timezone)

    if callable(candidate):
        return CallableClock(candidate, timezone=timezone)

    raise TypeError("CONFIG_CLOCK_INVALID: «نوع ساعت پشتیبانی نمی‌شود؛ لطفاً Clock یا callable ارسال کنید.»")


@dataclass(slots=True)
class CallableClock(Clock):
    """Adapter turning a call-able into a deterministic :class:`Clock`."""

    func: Callable[[], datetime]
    timezone: ZoneInfo = field(default_factory=lambda: validate_timezone(DEFAULT_TIMEZONE))

    def __init__(self, func: Callable[[], datetime], *, timezone: str = DEFAULT_TIMEZONE) -> None:
        object.__setattr__(self, "func", func)
        object.__setattr__(self, "timezone", validate_timezone(timezone))

    def now(self) -> datetime:
        return _coerce_aware(self.func(), timezone=self.timezone)


def tehran_clock(*, now_factory: Callable[[], datetime] | None = None) -> SystemClock:
    """Backward-compatible helper returning the Tehran :class:`SystemClock`."""

    return Clock.for_tehran(now_factory=now_factory)


__all__ = [
    "CallableClock",
    "Clock",
    "DEFAULT_TIMEZONE",
    "FrozenClock",
    "SupportsNow",
    "SystemClock",
    "ensure_clock",
    "tehran_clock",
    "validate_timezone",
]

