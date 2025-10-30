from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

# --- ماژول‌های حذف شده ---
# from sma.phase6_import_to_sabt.security.rbac import AuthorizationError, TokenRegistry
# --- پایان ماژول‌های حذف شده ---

from sma.core.retry import (
    AsyncSleeper,
    RetryExhaustedError,
    RetryPolicy,
    build_async_clock_sleeper,
    execute_with_retry_async,
)
from sma.phase6_import_to_sabt.middleware.metrics import MiddlewareMetrics
from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics
# from sma.phase6_import_to_sabt.security.rbac import AuthorizationError, TokenRegistry # حذف شد
from sma.phase6_import_to_sabt.app.clock import Clock
from sma.phase6_import_to_sabt.app.config import RateLimitConfig # احتمالاً دیگر نیاز نیست، اما برای اکنون می‌ماند
from sma.phase6_import_to_sabt.app.stores import KeyValueStore, decode_response, encode_response
from sma.phase6_import_to_sabt.app.timing import Timer
from sma.phase6_import_to_sabt.app.context import reset_correlation_id, set_correlation_id
from sma.phase6_import_to_sabt.app.utils import ensure_no_control_chars, normalize_token

logger = logging.getLogger(__name__)


TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, clock: Clock) -> None:  # type: ignore[override]
        super().__init__(app)
        self._clock = clock

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        header_value = request.headers.get("X-Request-ID")
        ensure_no_control_chars([header_value or ""])
        correlation_id = header_value or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        request.state.request_ts = self._clock.now()
        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers["X-Request-ID"] = correlation_id
        return response


# --- کلاس‌های امنیتی حذف شدند ---
# @dataclass
# class RateLimitState: ...

# class RateLimitMiddleware(BaseHTTPMiddleware): ...

# class IdempotencyMiddleware(BaseHTTPMiddleware): ...

# class AuthMiddleware(BaseHTTPMiddleware): ...
# --- پایان کلاس‌های امنیتی ---
# توضیح: کلاس‌های RateLimitMiddleware, IdempotencyMiddleware, AuthMiddleware کاملاً حذف شده‌اند.

class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, metrics: ServiceMetrics, timer: Timer) -> None:  # type: ignore[override]
        super().__init__(app)
        self._metrics = metrics
        self._timer = timer

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        handle = self._timer.start()
        response = await call_next(request)
        duration = handle.elapsed()
        self._metrics.request_latency.observe(duration)
        self._metrics.request_total.labels(
            method=request.method,
            path=request.url.path,
            status=str(response.status_code),
        ).inc()
        # حذف به‌روزرسانی diagnostics برای لایه‌های امنیتی
        # diagnostics = getattr(request.app.state, "diagnostics", None)
        # if diagnostics and diagnostics.get("enabled"):
        #     diagnostics["last_chain"] = getattr(request.state, "middleware_chain", [])
        # 'middleware_chain' دیگر به‌روزرسانی نمی‌شود زیرا لایه‌های امنیتی حذف شده‌اند
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, diagnostics) -> None:  # type: ignore[override]
        super().__init__(app)
        self._diagnostics_factory = diagnostics

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        logger.info(
            "request.completed",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", None),
                "component": "http",
                "outcome": response.status_code,
            },
        )
        # حذف به‌روزرسانی diagnostics برای لایه‌های امنیتی
        # diagnostics = self._diagnostics_factory()
        # if diagnostics and diagnostics.get("enabled"):
        #     diagnostics["last_chain"] = getattr(request.state, "middleware_chain", [])
        # 'middleware_chain' دیگر به‌روزرسانی نمی‌شود زیرا لایه‌های امنیتی حذف شده‌اند
        return response


__all__ = [
    "CorrelationIdMiddleware",
    # "RateLimitMiddleware", # حذف شد
    # "IdempotencyMiddleware", # حذف شد
    # "AuthMiddleware", # حذف شد
    "MetricsMiddleware",
    "RequestLoggingMiddleware",
]
