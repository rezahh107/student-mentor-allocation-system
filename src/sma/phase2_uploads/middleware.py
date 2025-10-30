from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
# from redis import Redis # دیگر مورد نیاز نیست
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# from .errors import envelope # دیگر مورد نیاز نیست یا فقط برای موارد امنیتی


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, redis=None, limit: int = 100, window_seconds: int = 60) -> None: # redis دیگر مورد نیاز نیست
        super().__init__(app)
        # self.redis = redis # حذف شد
        # self.limit = limit # حذف شد
        # self.window_seconds = window_seconds # حذف شد

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # افزودن 'rate' به زنجیره حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # chain.append("rate")
        # request.state.middleware_chain = chain
        # بررسی محدودیت حذف شد
        # rid = request.headers.get("X-Request-ID", "no-rid")
        # key = f"ratelimit:{rid}"
        # current = self.redis.incr(key)
        # if current == 1: ...
        # if current > self.limit: ...
        return await call_next(request) # تغییر داده شد


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # افزودن 'idem' به زنجیره حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # chain.append("idem")
        # request.state.middleware_chain = chain
        # بررسی Idempotency-Key حذف شد
        # if request.method in {"POST", "PUT"} and request.url.path.startswith("/uploads"):
        #     if "Idempotency-Key" not in request.headers: ...
        return await call_next(request) # تغییر داده شد


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # افزودن 'auth' به زنجیره حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # chain.append("auth")
        # request.state.middleware_chain = chain
        # بررسی Authorization حذف شد
        # token = request.headers.get("Authorization")
        # if token and not token.startswith("Bearer "): ...
        return await call_next(request) # تغییر داده شد
