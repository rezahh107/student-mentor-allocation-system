"""Backward-compatible re-export of clock utilities for application wiring."""

from ..clock import (
    CallableClock,
    Clock,
    FixedClock,
    SystemClock,
    build_system_clock,
    ensure_clock,
)

__all__ = [
    "Clock",
    "FixedClock",
    "SystemClock",
    "CallableClock",
    "build_system_clock",
    "ensure_clock",
]
