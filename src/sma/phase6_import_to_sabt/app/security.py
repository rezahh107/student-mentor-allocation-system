from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from sma.phase6_import_to_sabt.app.clock import Clock
from sma.phase6_import_to_sabt.app.config import AuthConfig, RateLimitConfig
from sma.phase6_import_to_sabt.app.utils import normalize_token
from sma.phase6_import_to_sabt.app.stores import KeyValueStore

logger = logging.getLogger(__name__)


def _ensure_chain(request: Request) -> list[str]:
    chain = getattr(request.state, "middleware_chain", None)
    if chain is None:
        chain = []
        request.state.middleware_chain = chain
    return chain


@dataclass(slots=True)
class _RateLimitSnapshot:
    remaining: int
    key: str
    window_seconds: int


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple deterministic rate limiter suitable for CI test environments."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: KeyValueStore,
        config: RateLimitConfig,
        clock: Clock,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._store = store
        self._config = config
        self._clock = clock

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        chain = _ensure_chain(request)
        chain.append("RateLimit")
        diagnostics = getattr(request.app.state, "diagnostics", None)
        identifier = (
            normalize_token(request.headers.get("X-RateLimit-Key"))
            or normalize_token(request.headers.get("X-Client-ID"))
            or (request.client.host if request.client else "anonymous")
        )
        bucket_key = f"{self._config.namespace}:{identifier}:{request.method.upper()}"
        penalty_key = f"penalty:{bucket_key}"
        penalty_active = await self._store.get(penalty_key)
        if penalty_active is not None:
            logger.warning(
                "ratelimit.blocked",
                extra={"correlation_id": getattr(request.state, "correlation_id", None), "key": identifier},
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "fa_error_envelope": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "تعداد درخواست‌ها از حد مجاز فراتر رفته است؛ لطفاً بعداً دوباره تلاش کنید.",
                    }
                },
            )
        attempts = await self._store.incr(bucket_key, self._config.window_seconds)
        remaining = max(self._config.requests - attempts, 0)
        snapshot = _RateLimitSnapshot(
            remaining=remaining,
            key=bucket_key,
            window_seconds=self._config.window_seconds,
        )
        request.state.rate_limit_state = snapshot
        if attempts > self._config.requests:
            await self._store.set(penalty_key, "1", self._config.penalty_seconds)
            raise HTTPException(
                status_code=429,
                detail={
                    "fa_error_envelope": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "حداکثر تعداد درخواست‌های مجاز مصرف شده است.",
                    }
                },
                headers={"Retry-After": str(self._config.penalty_seconds)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(snapshot.remaining)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_rate_limit"] = {
                "remaining": snapshot.remaining,
                "bucket": snapshot.key,
            }
        return response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Reject duplicate POST requests based on the Idempotency-Key header."""

    IDEMPOTENCY_TTL_SECONDS = 86_400

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: KeyValueStore,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._store = store

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        chain = _ensure_chain(request)
        chain.append("Idempotency")
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if request.method.upper() != "POST":
            return await call_next(request)
        key = normalize_token(request.headers.get("Idempotency-Key"))
        if not key:
            raise HTTPException(
                status_code=400,
                detail={
                    "fa_error_envelope": {
                        "code": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": "هدر Idempotency-Key الزامی است.",
                    }
                },
            )
        stored = await self._store.set_if_not_exists(
            key,
            value=str(self.IDEMPOTENCY_TTL_SECONDS),
            ttl_seconds=self.IDEMPOTENCY_TTL_SECONDS,
        )
        request.state.idempotency_state = {"key": key, "created": stored}
        if diagnostics and diagnostics.get("enabled"):
            diagnostics.setdefault("last_idempotency", {})[key] = "created" if stored else "duplicate"
        if not stored:
            raise HTTPException(
                status_code=409,
                detail={
                    "fa_error_envelope": {
                        "code": "IDEMPOTENCY_REPLAY",
                        "message": "این درخواست قبلاً پردازش شده است.",
                    }
                },
            )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token authentication middleware for service routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: AuthConfig,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._config = config

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        chain = _ensure_chain(request)
        chain.append("Auth")
        diagnostics = getattr(request.app.state, "diagnostics", None)
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
        expected = self._config.service_token
        allow_all = getattr(self._config, "allow_all", False)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_auth"] = {"present": bool(token), "allow_all": allow_all}
        if allow_all or request.url.path == "/metrics":
            request.state.auth_state = {
                "token": token,
                "skipped": True,
                "allow_all": allow_all,
            }
            return await call_next(request)
        if expected and token != expected:
            raise HTTPException(
                status_code=401,
                detail={
                    "fa_error_envelope": {
                        "code": "AUTH_TOKEN_INVALID",
                        "message": "توکن احراز هویت معتبر نیست.",
                    }
                },
            )
        request.state.auth_state = {"token": token}
        return await call_next(request)


__all__ = ["RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware"]
