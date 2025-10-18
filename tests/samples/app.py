from __future__ import annotations

from fastapi import FastAPI


class RateLimitMiddleware:  # pragma: no cover - dummy middleware
    pass


class IdempotencyMiddleware:  # pragma: no cover - dummy middleware
    pass


class AuthMiddleware:  # pragma: no cover - dummy middleware
    pass


app = FastAPI()
app.add_middleware(RateLimitMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(AuthMiddleware)
