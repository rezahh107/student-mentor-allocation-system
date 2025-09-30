from __future__ import annotations

"""
Deterministic clock utilities centered on IANA tz=Asia/Tehran.

- Keeps main's implementation (Clock, FixedClock, SystemClock, build_system_clock)
- Adds codex branch API surface (CallableClock, ensure_clock) for backward-compat
"""

import datetime as dt
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Protocol, runtime_checkable, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ----- Normalization helpers (from main) --------------------------------------

_PERSIAN_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
_ZERO_WIDTH_CHARACTERS = ("\u200c", "\u200d", "\ufeff")
_DEFAULT_TZ_NAME = "Asia/Tehran"


def _normalise_timezone_name(timezone: str) -> str:
    if timezone is None:
        raise ValueError("منطقهٔ زمانی نامعتبر است؛ مقدار ورودی: None")

    normalized = unicodedata.normalize("NFKC", str(timezone))
    normalized = normalized.translate(_PERSIAN_DIGIT_MAP).translate(_ARABIC_DIGIT_MAP)
    for character in _ZERO_WIDTH_CHARACTERS:
        normalized = normalized.replace(character, "")
    normalized = normalized.strip()

    if not normalized:
        raise ValueError("منطقهٔ زمانی نامعتبر است؛ مقدار ورودی خالی است.")
    if len(normalized) > 255:
        raise ValueError("منطقهٔ زمانی نامعتبر است؛ طول مقدار بیش از حد مجاز است.")

    return normalized


@lru_cache(maxsize=32)
def _load_zone_info(timezone: str) -> ZoneInfo:
    return ZoneInfo(timezone)


def _coerce_aware(value: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """
    Ensure the datetime is timezone-aware. If naive, attach provided tz.
    We deliberately do not convert aware values (no implicit zone change).
    """
    if not isinstance(value, dt.datetime):  # defensive
        raise TypeError("instant must be a datetime instance")
    return value if value.tzinfo is not None else value.replace(tzinfo=tz)


# ----- Public protocol (from main) --------------------------------------------

@runtime_checkable
class Clock(Protocol):
    """Protocol describing deterministic clock access."""
    def now(self) -> dt.datetime:
        """Return the current :class:`datetime.datetime` (aware when possible)."""


# ----- Implementations (from main) --------------------------------------------

@dataclass(frozen=True, slots=True)
class FixedClock:
    """Clock returning a pre-defined instant for deterministic behaviour."""
    instant: dt.datetime

    def now(self) -> dt.datetime:
        # For safety under determinism rules, attach Tehran tz if naive
        tz = _load_zone_info(_DEFAULT_TZ_NAME)
        return _coerce_aware(self.instant, tz)


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Clock backed by :class:`datetime.datetime.now` with an IANA timezone."""
    timezone: ZoneInfo
    _timezone_key: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, ZoneInfo):  # defensive
            raise TypeError("timezone must be a ZoneInfo instance")
        object.__setattr__(self, "_timezone_key", getattr(self.timezone, "key", str(self.timezone)))

    @property
    def timezone_name(self) -> str:
        """Return the canonical timezone key used for logging/debugging."""
        return self._timezone_key

    def now(self) -> dt.datetime:
        """Return the current timezone-aware datetime in the configured zone."""
        return dt.datetime.now(tz=self.timezone)


def build_system_clock(timezone: str) -> SystemClock:
    """Build a :class:`SystemClock` for the provided IANA timezone name."""
    normalized = _normalise_timezone_name(timezone)
    try:
        zone = _load_zone_info(normalized)
    except ZoneInfoNotFoundError as exc:  # exercised via tests
        raise ValueError(f"منطقهٔ زمانی نامعتبر است؛ مقدار ورودی: {normalized}.") from exc
    return SystemClock(timezone=zone)


# ----- Back-compat layer (codex branch API) -----------------------------------

@dataclass(frozen=True, slots=True)
class CallableClock:
    """
    Adapter that wraps a zero-arg callable returning datetime into a Clock.
    Ensures returned instants are aware (defaults to Asia/Tehran if naive).
    """
    func: Callable[[], dt.datetime]

    def now(self) -> dt.datetime:
        tz = _load_zone_info(_DEFAULT_TZ_NAME)
        return _coerce_aware(self.func(), tz)


def ensure_clock(
    candidate: Union[Clock, Callable[[], dt.datetime], None],
    *,
    default_timezone: str = _DEFAULT_TZ_NAME,
) -> Clock:
    """
    Accepts a Clock instance, a zero-arg callable returning datetime, or None.
    - If None: returns SystemClock in the given default IANA tz.
    - If callable: wraps in CallableClock and coerces to aware datetimes.
    - If Clock: returns as-is.
    """
    if candidate is None:
        return build_system_clock(default_timezone)
    if isinstance(candidate, Clock):
        return candidate
    if callable(candidate):
        return CallableClock(candidate)  # type: ignore[arg-type]
    raise TypeError("Unsupported clock type; expected Clock, callable, or None.")


__all__ = [
    "Clock",
    "FixedClock",
    "SystemClock",
    "CallableClock",
    "build_system_clock",
    "ensure_clock",
]
