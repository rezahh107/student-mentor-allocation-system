from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_PERSIAN_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
_ZERO_WIDTH_CHARACTERS = ("\u200c", "\u200d", "\ufeff")


@runtime_checkable
class Clock(Protocol):
    """Protocol describing deterministic clock access."""

    def now(self) -> dt.datetime:
        """Return the current :class:`datetime.datetime` (aware when possible)."""


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Clock returning a pre-defined instant for deterministic behaviour."""

    instant: dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.instant, dt.datetime):  # pragma: no cover - defensive
            raise TypeError("instant must be a datetime instance")

    def now(self) -> dt.datetime:
        """Return the injected instant as-is."""

        return self.instant


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Clock backed by :class:`datetime.datetime.now` with an IANA timezone."""

    timezone: ZoneInfo
    _timezone_key: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, ZoneInfo):  # pragma: no cover - defensive
            raise TypeError("timezone must be a ZoneInfo instance")
        object.__setattr__(self, "_timezone_key", getattr(self.timezone, "key", str(self.timezone)))

    @property
    def timezone_name(self) -> str:
        """Return the canonical timezone key used for logging/debugging."""

        return self._timezone_key

    def now(self) -> dt.datetime:
        """Return the current timezone-aware datetime in the configured zone."""

        return dt.datetime.now(tz=self.timezone)


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


def build_system_clock(timezone: str) -> SystemClock:
    """Build a :class:`SystemClock` for the provided IANA timezone name."""

    normalized = _normalise_timezone_name(timezone)
    try:
        zone = _load_zone_info(normalized)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - exercised via tests
        raise ValueError(f"منطقهٔ زمانی نامعتبر است؛ مقدار ورودی: {normalized}.") from exc

    return SystemClock(timezone=zone)


__all__ = ["Clock", "FixedClock", "SystemClock", "build_system_clock"]
