from __future__ import annotations

import os
from typing import Mapping

from sma.core.clock import Clock, ensure_clock


def get_rate_limit_info() -> Mapping[str, str]:  # pragma: no cover - placeholder for integrations
    return {"bucket": "default", "remaining": "∞"}


def get_middleware_chain() -> list[str]:
    from .middleware import middleware_order

    return middleware_order()


def get_debug_context(*, clock: Clock | None = None) -> dict[str, object]:
    active_clock = ensure_clock(clock, default=Clock.for_tehran())
    return {
        "redis_keys": [],
        "rate_limit_state": get_rate_limit_info(),
        "middleware_order": get_middleware_chain(),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": active_clock.unix_timestamp(),
    }
