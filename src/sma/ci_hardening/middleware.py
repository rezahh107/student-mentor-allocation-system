"""Deterministic middleware chain for RateLimit → Idempotency → Auth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CollectorRegistry, Counter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .retry import RetryConfig, backoff_durations
from .state import InMemoryStore


@dataclass
class MiddlewareDiagnostics:
    """Tracks middleware execution for deterministic assertions.

    Attributes:
        order: Ordered list of middleware names as executed for the request.
        rate_limit_hits: Number of successful rate-limit grants observed.
        backoff_history: Backoff values computed for each retry attempt.
        idempotency_keys: Collected idempotency keys encountered during the
            request lifecycle.
        auth_tokens: Authentication tokens observed for debugging purposes.
        correlation_ids: Correlation identifiers attached to processed
            requests.
    """

    order: list[str] = field(default_factory=list)
    rate_limit_hits: int = 0
    backoff_history: list[float] = field(default_factory=list)
    idempotency_keys: set[str] = field(default_factory=set)
    auth_tokens: list[str] = field(default_factory=list)
    correlation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RateLimitRule:
    """Represents a single rate limit rule.

    Attributes:
        limit: Number of allowed requests per window.
        window_seconds: Size of the rate-limiting window in seconds.
    """

    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate limiting configuration.

    Attributes:
        namespace: Namespace prefix for metric and key isolation.
        rules: Tuple containing all applicable rate limit rules.
    """

    namespace: str
    rules: tuple[RateLimitRule, ...]


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration.

    Attributes:
        allowed_tokens: Tuple of bearer tokens authorised for requests.
    """

    allowed_tokens: tuple[str, ...]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter for deterministic CI tests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: InMemoryStore,
        config: RateLimitConfig,
        retry: RetryConfig,
        registry: CollectorRegistry | None = None,
    ) -> None:
        """Initialise the rate limiter.

        Args:
            app: Wrapped ASGI application.
            store: Storage backend tracking request counts.
            config: Rate limiting configuration namespace and rules.
            retry: Retry configuration controlling attempt counts.
            registry: Optional Prometheus registry for metric isolation.
        """

        super().__init__(app)
        self._store = store
        self._config = config
        self._retry = retry
        resolved_registry = registry or getattr(
            getattr(app, "state", object()), "registry", None
        )
        self._attempts = Counter(
            "ci_rate_limit_attempts",
            "Total rate limit attempts segmented by outcome.",
            ("namespace", "status"),
            registry=None,
        )
        if resolved_registry is not None:
            try:
                resolved_registry.register(self._attempts)
            except ValueError:  # pragma: no cover - already registered
                pass

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process the request enforcing rate limits.

        Args:
            request: Incoming FastAPI request instance.
            call_next: Downstream handler invoked on success.

        Returns:
            Response returned by the downstream handler or a ``429`` response
            when limits are exceeded.
        """

        diagnostics = ensure_diagnostics(request)
        diagnostics.order.append("RateLimit")
        key = request.headers.get("X-RateLimit-Key") or (
            request.client.host if request.client else "anonymous"
        )
        correlation_id = _resolve_correlation_id(request)
        diagnostics.correlation_ids.append(correlation_id)
        bucket_key = f"{self._config.namespace}:{key}:{request.method}"
        seed = f"{bucket_key}:{correlation_id}"
        allowed = False
        for delay in backoff_durations(seed, self._retry):
            self._record_metric(status="attempt")
            diagnostics.backoff_history.append(delay)
            hits_text = self._store.get(bucket_key)
            hits = int(hits_text) if hits_text else 0
            if hits < self._config.rules[0].limit:
                self._store.set(bucket_key, str(hits + 1))
                diagnostics.rate_limit_hits += 1
                self._record_metric(status="granted")
                allowed = True
                break
        if not allowed:
            self._record_metric(status="exhausted")
            return Response(status_code=429)
        response = await call_next(request)
        return response

    def _record_metric(self, *, status: str) -> None:
        """Increment retry metrics when a registry is configured.

        Args:
            status: Outcome label for the metric sample.
        """

        try:
            self._attempts.labels(namespace=self._config.namespace, status=status).inc()
        except ValueError:  # pragma: no cover - duplicate registration safety
            pass


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Ensures POST requests are idempotent using the configured store."""

    def __init__(self, app: ASGIApp, *, store: InMemoryStore) -> None:
        """Initialise middleware.

        Args:
            app: Wrapped ASGI application.
            store: Storage backend used to persist idempotency keys.
        """

        super().__init__(app)
        self._store = store

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject duplicate POST requests based on idempotency keys.

        Args:
            request: Incoming FastAPI request.
            call_next: Downstream handler to invoke when permitted.

        Returns:
            Response from the downstream handler or ``409`` on duplicates.
        """

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

    def __init__(self, app: ASGIApp, *, config: AuthConfig) -> None:
        """Initialise middleware.

        Args:
            app: Wrapped ASGI application.
            config: Authentication configuration containing valid tokens.
        """

        super().__init__(app)
        self._config = config

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Authenticate incoming requests using bearer tokens.

        Args:
            request: Incoming request object.
            call_next: Downstream handler invoked upon successful auth.

        Returns:
            Response generated by downstream handler or ``401`` on failure.
        """

        diagnostics = ensure_diagnostics(request)
        diagnostics.order.append("Auth")
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ")
        diagnostics.auth_tokens.append(token)
        if token not in self._config.allowed_tokens:
            return Response(status_code=401)
        return await call_next(request)


def ensure_diagnostics(request: Request) -> MiddlewareDiagnostics:
    """Ensure diagnostics object is available on the request state.

    Args:
        request: Request whose state should expose diagnostics.

    Returns:
        Existing ``MiddlewareDiagnostics`` instance or a newly created one.
    """

    diagnostics: MiddlewareDiagnostics | None = getattr(
        request.state, "diagnostics", None
    )
    if diagnostics is None:
        diagnostics = MiddlewareDiagnostics()
        request.state.diagnostics = diagnostics
    return diagnostics


def _resolve_correlation_id(request: Request) -> str:
    """Return a deterministic correlation identifier for retries.

    Args:
        request: Incoming request for which the identifier is required.

    Returns:
        Correlation identifier resolved from headers or derived from method
        and path.
    """

    header = request.headers.get("X-Correlation-ID")
    if header:
        return header
    fallback = request.headers.get("X-Request-ID")
    if fallback:
        return fallback
    return f"{request.method}:{request.url.path}"


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
