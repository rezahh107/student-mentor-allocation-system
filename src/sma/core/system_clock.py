"""Process wall-clock access confined to core package."""
from __future__ import annotations

from datetime import UTC, datetime


def system_now() -> datetime:
    """Return the current UTC datetime using the process wall clock."""

    return datetime.now(UTC)


__all__ = ["system_now"]
