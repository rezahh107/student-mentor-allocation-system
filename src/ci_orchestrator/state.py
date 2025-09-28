from __future__ import annotations

import os
import time
from typing import Mapping


def get_rate_limit_info() -> Mapping[str, str]:  # pragma: no cover - placeholder for integrations
    return {"bucket": "default", "remaining": "∞"}


def get_middleware_chain() -> list[str]:
    from .middleware import middleware_order

    return middleware_order()


def get_debug_context() -> dict[str, object]:
    return {
        "redis_keys": [],
        "rate_limit_state": get_rate_limit_info(),
        "middleware_order": get_middleware_chain(),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": time.time(),
    }
