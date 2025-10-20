"""ابزارهای زمانی برای استفاده سراسری با آگاهی از منطقه زمانی."""
from __future__ import annotations

from datetime import UTC

from sma.core.clock import tehran_clock


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp compliant with Python 3.11 APIs."""

    return tehran_clock().now().astimezone(UTC)


__all__ = ["utc_now"]

