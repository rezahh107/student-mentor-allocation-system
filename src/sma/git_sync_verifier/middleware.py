"""Middleware pipeline ensuring RateLimit → Idempotency → Auth ordering."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .clock import Clock
from .constants import REMOTE_REGEX
from .logging_utils import mask_path
from .metrics import SyncMetrics


class MiddlewareError(RuntimeError):
    """Raised when middleware validation fails."""


class FetchCallable(Protocol):
    """Callable signature for executing git fetch."""

    def __call__(self, ctx: "FetchContext") -> "FetchResult":
        ...


class GitFetchMiddleware(Protocol):
    """Middleware protocol."""

    name: str

    def invoke(self, ctx: "FetchContext", call_next: FetchCallable) -> "FetchResult":
        ...


@dataclass
class FetchResult:
    """Result of fetch pipeline."""

    success: bool
    return_code: int | None = None
    stderr: str | None = None


@dataclass
class FetchContext:
    """Context passed through middleware chain."""

    repo_path: Path
    remote: str
    remote_url: str
    timeout: int
    correlation_id: str
    logger: any
    clock: Clock
    metrics: SyncMetrics
    middleware_trace: list[str] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=dict)
    fetch_attempts: int = 0
    fetch_retries: int = 0


class RateLimitMiddleware:
    """Prevent overly frequent fetch attempts."""

    name = "RateLimit"

    def __init__(self, min_interval_ms: int = 150) -> None:
        self._min_interval_ms = min_interval_ms
        self._lock = threading.Lock()
        self._last_call: dict[str, int] = {}

    def invoke(self, ctx: FetchContext, call_next: FetchCallable) -> FetchResult:
        ctx.middleware_trace.append(self.name)
        now_ms = ctx.clock.monotonic_ms()
        with self._lock:
            last_ms = self._last_call.get(ctx.remote_url)
            if last_ms is not None and now_ms - last_ms < self._min_interval_ms:
                ctx.logger.info(
                    "rate_limit.deferred",
                    extra={
                        "correlation_id": ctx.correlation_id,
                        "wait_ms": self._min_interval_ms - (now_ms - last_ms),
                    },
                )
            self._last_call[ctx.remote_url] = now_ms
        return call_next(ctx)


class IdempotencyMiddleware:
    """Record idempotency metadata while allowing safe retries."""

    name = "Idempotency"

    def __init__(self, ttl_ms: int = 24 * 60 * 60 * 1000) -> None:
        self._ttl_ms = ttl_ms
        self._entries: dict[str, int] = {}
        self._lock = threading.Lock()

    def invoke(self, ctx: FetchContext, call_next: FetchCallable) -> FetchResult:
        ctx.middleware_trace.append(self.name)
        key = f"{mask_path(ctx.repo_path)}::{ctx.remote_url}"
        now_ms = ctx.clock.monotonic_ms()
        with self._lock:
            timestamp = self._entries.get(key)
            hit = bool(timestamp and now_ms - timestamp < self._ttl_ms)
            self._entries[key] = now_ms
        ctx.logger.info(
            "idempotency.recorded",
            extra={
                "correlation_id": ctx.correlation_id,
                "key": key,
                "ttl_ms": self._ttl_ms,
                "cache_hit": hit,
            },
        )
        return call_next(ctx)


class AuthMiddleware:
    """Validate remote configuration before executing fetch."""

    name = "Auth"

    def invoke(self, ctx: FetchContext, call_next: FetchCallable) -> FetchResult:
        ctx.middleware_trace.append(self.name)
        if not REMOTE_REGEX.fullmatch(ctx.remote_url):
            raise MiddlewareError("remote does not match allowed pattern")
        return call_next(ctx)


class MiddlewareChain:
    """Compose middleware in the required order."""

    def __init__(self, middlewares: list[GitFetchMiddleware], final_callable: FetchCallable) -> None:
        self._middlewares = middlewares
        self._final_callable = final_callable

    def execute(self, ctx: FetchContext) -> FetchResult:
        """Execute middleware chain."""
        return self._call_next(0, ctx)

    def _call_next(self, index: int, ctx: FetchContext) -> FetchResult:
        if index >= len(self._middlewares):
            return self._final_callable(ctx)
        middleware = self._middlewares[index]
        return middleware.invoke(ctx, lambda next_ctx: self._call_next(index + 1, next_ctx))


def build_default_chain(final_callable: FetchCallable) -> MiddlewareChain:
    """Construct middleware chain with required order."""
    middlewares: list[GitFetchMiddleware] = [
        RateLimitMiddleware(),
        IdempotencyMiddleware(),
        AuthMiddleware(),
    ]
    return MiddlewareChain(middlewares, final_callable)
