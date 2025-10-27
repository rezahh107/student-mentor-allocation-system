"""Deterministic middleware chain for RateLimit → Idempotency → Auth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .retry import RetryConfig, backoff_durations
from .state import InMemoryStore


@dataclass
class MiddlewareDiagnostics:
    """Tracks middleware execution for deterministic assertions."""

    order: list[str] = field(default_factory=list)
    rate_limit_hits: int = 0
    backoff_history: list[float] = field(default_factory=list)
    idempotency_keys: set[str] = field(default_factory=set)
    auth_tokens: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RateLimitRule:
    """Represents a single rate limit rule."""

    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate limiting configuration."""

    namespace: str
    rules: tuple[RateLimitRule, ...]


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration."""

    allowed_tokens: tuple[str, ...]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter for deterministic CI tests."""

    def __init__(
        self,
        app,
        *,
        store: InMemoryStore,
        config: RateLimitConfig,
        retry: RetryConfig,
    ) -> None:
        super().__init__(app)
        self._store = store
        self._config = config
        self._retry = retry

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        diagnostics = ensure_diagnostics(request)
        diagnostics.order.append("RateLimit")
        key = request.headers.get("X-RateLimit-Key") or (
            request.client.host if request.client else "anonymous"
        )
        allowed = False
        for attempt, delay in enumerate(backoff_durations(key, self._retry), start=1):
            bucket_key = f"{self._config.namespace}:{key}:{request.method}"
            hits_text = self._store.get(bucket_key)
            hits = int(hits_text) if hits_text else 0
            if hits < self._config.rules[0].limit:
                self._store.set(bucket_key, str(hits + 1))
                diagnostics.rate_limit_hits += 1
                diagnostics.backoff_history.append(delay)
                allowed = True
                break
        if not allowed:
            return Response(status_code=429)
        response = await call_next(request)
        return response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Ensures POST requests are idempotent using the configured store."""

    def __init__(self, app, *, store: InMemoryStore) -> None:
        super().__init__(app)
        self._store = store

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        diagnostics = ensure_diagnostics(request)
        diagnostics.order.append("Idempotency")
        if request.method.upper() != "POST":
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            key = f"auto:{request.url.path}:{len(diagnostics.idempotency_keys)}"
        if self._store.get(key):
            return Response(status_code=409)
        self._store.set(key, "1")
        diagnostics.idempotency_keys.add(key)
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token based authentication middleware."""

    def __init__(self, app, *, config: AuthConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        diagnostics = ensure_diagnostics(request)
        diagnostics.order.append("Auth")
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ")
        diagnostics.auth_tokens.append(token)
        if token not in self._config.allowed_tokens:
            return Response(status_code=401)
        return await call_next(request)


def ensure_diagnostics(request: Request) -> MiddlewareDiagnostics:
    """Ensure diagnostics object is available on the request state."""

    diagnostics: MiddlewareDiagnostics | None = getattr(
        request.state, "diagnostics", None
    )
    if diagnostics is None:
        diagnostics = MiddlewareDiagnostics()
        request.state.diagnostics = diagnostics
    return diagnostics


__all__ = [
    "AuthConfig",
    "AuthMiddleware",
    "IdempotencyMiddleware",
    "MiddlewareDiagnostics",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "RateLimitRule",
    "ensure_diagnostics",
]
