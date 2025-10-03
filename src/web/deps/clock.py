"""FastAPI dependency helpers for the Tehran system clock."""
from __future__ import annotations

import contextlib
import threading
from typing import Iterator

from fastapi import Depends

from src.core.clock import Clock, ensure_clock

_LOCK = threading.Lock()
_ACTIVE_CLOCK: Clock | None = None


def _build_default_clock() -> Clock:
    return Clock.for_tehran()


def get_clock() -> Clock:
    """Return the process-wide Tehran clock singleton."""

    global _ACTIVE_CLOCK
    with _LOCK:
        if _ACTIVE_CLOCK is None:
            _ACTIVE_CLOCK = _build_default_clock()
        return _ACTIVE_CLOCK


def provide_clock() -> Clock:
    """Compatibility helper for FastAPI ``Depends`` usage."""

    return get_clock()


def injected_clock(clock: Clock = Depends(provide_clock)) -> Clock:
    """Explicit dependency to inject the shared Tehran clock."""

    return clock


@contextlib.contextmanager
def override_clock(clock: Clock | None) -> Iterator[Clock]:
    """Temporarily override the global clock (used in tests)."""

    global _ACTIVE_CLOCK
    with _LOCK:
        previous = _ACTIVE_CLOCK
        _ACTIVE_CLOCK = ensure_clock(clock, default=_build_default_clock())
    try:
        yield _ACTIVE_CLOCK
    finally:
        with _LOCK:
            _ACTIVE_CLOCK = previous
