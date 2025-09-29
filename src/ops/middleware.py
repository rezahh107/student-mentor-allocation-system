from __future__ import annotations

MIDDLEWARE_CHAIN = ("RateLimit", "Idempotency", "Auth")

__all__ = ["MIDDLEWARE_CHAIN"]
