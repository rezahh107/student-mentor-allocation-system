from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from redis import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .errors import envelope


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, redis: Redis, limit: int = 100, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        chain = getattr(request.state, "middleware_chain", [])
        chain.append("rate")
        request.state.middleware_chain = chain
        rid = request.headers.get("X-Request-ID", "no-rid")
        key = f"ratelimit:{rid}"
        current = self.redis.incr(key)
        if current == 1:
            self.redis.expire(key, self.window_seconds)
        if current > self.limit:
            return JSONResponse(
                envelope(
                    "UPLOAD_VALIDATION_ERROR",
                    details={"reason": "RATE_LIMIT"},
                ).to_dict(),
                status_code=429,
            )
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        chain = getattr(request.state, "middleware_chain", [])
        chain.append("idem")
        request.state.middleware_chain = chain
        if request.method in {"POST", "PUT"} and request.url.path.startswith("/uploads"):
            if "Idempotency-Key" not in request.headers:
                return JSONResponse(
                    envelope(
                        "UPLOAD_VALIDATION_ERROR",
                        details={"reason": "IDEMPOTENCY_KEY_REQUIRED"},
                    ).to_dict(),
                    status_code=400,
                )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        chain = getattr(request.state, "middleware_chain", [])
        chain.append("auth")
        request.state.middleware_chain = chain
        token = request.headers.get("Authorization")
        if token and not token.startswith("Bearer "):
            return JSONResponse(
                envelope(
                    "UPLOAD_VALIDATION_ERROR",
                    details={"reason": "AUTH_INVALID"},
                ).to_dict(),
                status_code=401,
            )
        return await call_next(request)
