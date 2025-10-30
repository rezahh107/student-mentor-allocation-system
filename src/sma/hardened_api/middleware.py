"""Security-focused middleware for the hardened Student Allocation API."""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Iterator, Protocol

from fastapi import HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from sma.core.clock import Clock, ensure_clock
# from .observability import ( # حذف شد یا تغییر کرد
#     StructuredLogger,
#     emit_log,
#     get_metric,
#     hash_national_id, # ممکن است فقط برای امنیت/PII باشد
#     mask_phone, # ممکن است فقط برای امنیت/PII باشد
# )
# from .redis_support import ( # حذف شد یا تغییر کرد
#     IdempotencyConflictError,
#     RedisIdempotencyRepository,
#     RedisNamespaces,
#     RedisSlidingWindowLimiter,
#     RedisOperationError,
#     JWTDenyList,
# )

# --- تعاریف موقت یا حذف شده ---
# APIKeyRepository, AuthConfig, RateLimitRule, RateLimitConfig, و ...
# باید با ساختارهای جدید یا خالی جایگزین شوند

class DummyAPIKeyRepository:
    async def is_active(self, hashed_key: str) -> bool: return True

@dataclass(slots=True)
class DummyAuthConfig:
    # فقط برای جلوگیری از خطا
    pass

@dataclass(slots=True)
class DummyRateLimitRule:
    # فقط برای جلوگیری از خطا
    pass

@dataclass(slots=True)
class DummyRateLimitConfig:
    # فقط برای جلوگیری از خطا
    pass

def snapshot_rate_limit_config(config) -> Any: return None
def restore_rate_limit_config(config, snapshot) -> None: pass
def ensure_rate_limit_config_restored(config, snapshot, *, context=None) -> None: pass
@contextmanager
def rate_limit_config_guard(config) -> Iterator[Any]: yield config

@dataclass(slots=True)
class DummyMiddlewareState:
    # logger: StructuredLogger # حذف شد یا تغییر کرد
    # auth_config: AuthConfig # حذف شد یا تغییر کرد
    # rate_limit_config: RateLimitConfig # حذف شد یا تغییر کرد
    # metrics_token: str | None # حذف شد یا تغییر کرد
    # metrics_ip_allowlist: set[str] # حذف شد یا تغییر کرد
    # max_body_bytes: int # حذف شد یا تغییر کرد
    # namespaces: RedisNamespaces # حذف شد یا تغییر کرد
    # rate_limiter: RedisSlidingWindowLimiter # حذف شد یا تغییر کرد
    # idempotency_repository: RedisIdempotencyRepository # حذف شد یا تغییر کرد
    pass

def get_rate_limit_info() -> dict[str, Any]: return {"mode": "disabled"}

def get_middleware_chain(app: ASGIApp) -> list[str]:
    chain: list[str] = []
    current = getattr(app, "middleware_stack", None)
    while current is not None:
        handler = getattr(current, "app", None)
        if isinstance(handler, BaseHTTPMiddleware):
            chain.append(handler.__class__.__name__)
        current = getattr(current, "app", None)
    return chain

def derive_correlation_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    if header and _ASCII_TOKEN_RE.fullmatch(header):
        return header
    return str(uuid.uuid4())

# توابع مرتبط با JWT حذف شدند
# async def _parse_jwt(token: str) -> dict[str, Any]: ...
# def _pad_b64(value: str) -> bytes: ...
# async def _validate_jwt(...) -> tuple[str, dict[str, Any]]: ...

# تابع احراز هویت حذف شد
# async def authenticate_request(request: Request, config: AuthConfig) -> tuple[str, str]: ...

# --- پایان تعاریف موقت یا حذف شده ---


_ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$") # ممکن است همچنان مورد استفاده قرار گیرد یا نیازی نباشد


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.correlation_id = derive_correlation_id(request)
        request.state.request_id = request.headers.get("X-Request-ID")
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

# --- حذف میدلویرهای امنیتی ---
# class SecurityHeadersMiddleware(BaseHTTPMiddleware): ...
# class RateLimitMiddleware(BaseHTTPMiddleware): ...
# class IdempotencyMiddleware(BaseHTTPMiddleware): ...
# class AuthenticationMiddleware(BaseHTTPMiddleware): ...
# --- پایان حذف ---

class TraceProbeMiddleware(BaseHTTPMiddleware):
    """Capture deterministic middleware traversal for observability and tests."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # trace: list[str] = [] # فقط اگر میدلویرهای امنیتی وجود داشته باشند معنی دارد
        # request.state.middleware_trace = trace
        request.state.middleware_chain = tuple() # خالی
        probe_enabled = request.headers.get("X-Debug-MW-Probe", "").lower() == "trace"
        try:
            response = await call_next(request)
        finally:
            # request.state.middleware_chain = tuple(trace) # فقط اگر trace تعریف شده باشد
            pass
        if probe_enabled:
            correlation_id = getattr(request.state, "correlation_id", None) or response.headers.get(
                "X-Correlation-ID",
                "-",
            )
            # joined = ">".join(trace) # فقط اگر trace تعریف شده باشد
            joined = "" # یا فقط نام میدلویر فعلی
            response.headers["X-MW-Trace"] = f"{correlation_id}|{joined}"
        return response


# توابع مرتبط با احراز هویت حذف شدند
# async def authenticate_request(...) -> tuple[str, str]: ...
# async def _validate_jwt(...) -> tuple[str, dict[str, Any]]: ...


def setup_middlewares(app: ASGIApp, *, state: MiddlewareState, allowed_origins: Iterable[str]) -> None:
    # فقط میدلویرهای غیرامنیتی اضافه می‌شوند
    # from .middleware_chain import install_middleware_chain
    # install_middleware_chain(app, state=state, allowed_origins=allowed_origins)
    # یا به صورت مستقیم:
    # app.add_middleware(CORSMiddleware, ...) # اگر لازم باشد
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(TraceProbeMiddleware)
    # دیگر میدلویرهای امنیتی حذف شده‌اند
    pass # این تابع باید با تغییرات هماهنگ شود یا کاملاً تغییر کند


async def finalize_response(
    request: Request,
    response: Response,
    *,
    # logger: StructuredLogger, # حذف شد یا تغییر کرد
    status_code: int,
    # error_code: str | None = None, # ممکن است حذف شود
    outcome: str,
) -> None:
    # consumer_id = getattr(request.state, "consumer_id", "anonymous") # حذف شد یا تغییر کرد
    consumer_id = "dev-anonymous" # مقدار پیش‌فرض
    correlation_id = getattr(request.state, "correlation_id", "-")
    request_id = getattr(request.state, "request_id", None)
    duration_ms = (time.perf_counter() - getattr(request.state, "_start_time", time.perf_counter())) * 1000
    # emit_log(...) # حذف شد یا تغییر کرد
    # فقط لاگ ساده یا هیچ
    print(f"Request {correlation_id} completed with status {status_code}, outcome {outcome}, latency {duration_ms:.2f}ms") # یا حذف شود
    # if consumer_id.startswith("09"): ... # mask_phone حذف شد


def get_client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return os.getenv("GITHUB_RUNNER_IP", "127.0.0.1")
