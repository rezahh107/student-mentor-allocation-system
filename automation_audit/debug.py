from __future__ import annotations

import os
import time
from typing import Any, Dict

import redis

from .ratelimit import RateLimiter


def get_debug_context(redis_client: redis.Redis, limiter: RateLimiter) -> Dict[str, Any]:
    return {
        "redis_keys": sorted(k.decode() if isinstance(k, bytes) else k for k in redis_client.keys("*")),
        "rate_limit_state": limiter.config.namespace,
        "middleware_order": ["RateLimit", "Idempotency", "Auth"],
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": time.time(),
    }
