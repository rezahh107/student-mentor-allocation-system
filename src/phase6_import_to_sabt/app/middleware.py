from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from core.retry import (
    AsyncSleeper,
    RetryExhaustedError,
    RetryPolicy,
    build_async_clock_sleeper,
    execute_with_retry_async,
)
from phase6_import_to_sabt.middleware.metrics import MiddlewareMetrics
from phase6_import_to_sabt.obs.metrics import ServiceMetrics
from phase6_import_to_sabt.security.rbac import AuthorizationError, TokenRegistry
from phase6_import_to_sabt.app.clock import Clock
from phase6_import_to_sabt.app.config import RateLimitConfig
from phase6_import_to_sabt.app.stores import KeyValueStore, decode_response, encode_response
from phase6_import_to_sabt.app.timing import Timer
from phase6_import_to_sabt.app.utils import ensure_no_control_chars, normalize_token

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
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response


@dataclass
class RateLimitState:
    exceeded: bool
    remaining: int


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        store: KeyValueStore,
        config: RateLimitConfig,
        clock: Clock,
        metrics: MiddlewareMetrics,
        timer: Timer,
        *,
        retry_policy: RetryPolicy | None = None,
        sleeper: AsyncSleeper | None = None,
        retryable: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._store = store
        self._config = config
        self._clock = clock
        self._metrics = metrics
        self._timer = timer
        self._retry_policy = retry_policy or RetryPolicy()
        self._retryable = retryable
        self._sleeper = sleeper or build_async_clock_sleeper(clock)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.middleware_chain = getattr(request.state, "middleware_chain", []) + ["RateLimit"]
        handle = self._timer.start()
        decision = "allow"
        route = request.url.path
        capacity = self._config.requests
        if route in {"/healthz", "/readyz", "/metrics"} or route.startswith("/ui/"):
            duration = handle.elapsed()
            self._metrics.observe_rate_limit(
                "bypass",
                duration,
                route=route,
                remaining=capacity,
                capacity=capacity,
            )
            diagnostics = getattr(request.app.state, "diagnostics", None)
            if diagnostics and diagnostics.get("enabled"):
                diagnostics["last_rate_limit"] = {"decision": "bypass", "duration": duration}
            return await call_next(request)
        identifier = request.headers.get("X-Client-ID") or request.client.host if request.client else "anonymous"
        ensure_no_control_chars([identifier])
        bucket = f"{self._config.namespace}:rl:{identifier}:{int(self._clock.now().timestamp()) // self._config.window_seconds}"
        try:
            current = await self._with_retry(
                request,
                op="ratelimit.incr",
                func=lambda: self._store.incr(bucket, ttl_seconds=self._config.window_seconds),
            )
        except RetryExhaustedError as exc:
            return self._retry_failure(
                request,
                handle,
                route,
                capacity,
                exc,
                namespace=bucket,
            )
        remaining = max(self._config.requests - current, 0)
        if current > self._config.requests:
            logger.warning("rate.limit.exceeded", extra={"correlation_id": getattr(request.state, "correlation_id", None)})
            retry_after = str(self._config.penalty_seconds)
            decision = "block"
            duration = handle.elapsed()
            self._metrics.observe_rate_limit(
                decision,
                duration,
                route=route,
                remaining=0,
                capacity=capacity,
            )
            diagnostics = getattr(request.app.state, "diagnostics", None)
            if diagnostics and diagnostics.get("enabled"):
                diagnostics["last_rate_limit"] = {"decision": decision, "duration": duration}
            return JSONResponse(
                status_code=429,
                content={
                    "fa_error_envelope": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "درخواست‌های شما بیش از حد مجاز است. لطفاً بعداً تلاش کنید.",
                    }
                },
                headers={"Retry-After": retry_after},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        duration = handle.elapsed()
        self._metrics.observe_rate_limit(
            decision,
            duration,
            route=route,
            remaining=remaining,
            capacity=capacity,
        )
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_rate_limit"] = {"decision": decision, "duration": duration}
        return response

    async def _with_retry(self, request: Request, *, op: str, func: Callable[[], Awaitable[Any]]) -> Any:
        correlation_id = getattr(request.state, "correlation_id", "ratelimit-missing")
        return await execute_with_retry_async(
            func,
            policy=self._retry_policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=self._retryable,
            correlation_id=correlation_id,
            op=op,
        )

    def _retry_failure(
        self,
        request: Request,
        handle,
        route: str,
        capacity: int,
        exc: RetryExhaustedError,
        *,
        namespace: str,
    ) -> Response:
        duration = handle.elapsed()
        self._metrics.observe_rate_limit(
            "error",
            duration,
            route=route,
            remaining=capacity,
            capacity=capacity,
        )
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_rate_limit"] = {
                "decision": "error",
                "duration": duration,
                "last_error": str(exc.last_error),
            }
        logger.error(
            "rate.limit.retry_exhausted",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", None),
                "op": exc.op,
                "namespace": namespace,
                "last_error": str(exc.last_error),
                "retry_attempts": self._retry_policy.max_attempts,
            },
        )
        return JSONResponse(
            status_code=503,
            content={
                "fa_error_envelope": {
                    "code": "RETRY_EXHAUSTED",
                    "message": "در حال حاضر امکان انجام عملیات نیست؛ لطفاً بعداً دوباره تلاش کنید.",
                }
            },
        )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        app,
        store: KeyValueStore,
        metrics: MiddlewareMetrics,
        timer: Timer,
        *,
        clock: Clock,
        retry_policy: RetryPolicy | None = None,
        sleeper: AsyncSleeper | None = None,
        retryable: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._store = store
        self._metrics = metrics
        self._timer = timer
        self._clock = clock
        self._retry_policy = retry_policy or RetryPolicy()
        self._retryable = retryable
        self._sleeper = sleeper or build_async_clock_sleeper(clock)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        chain = getattr(request.state, "middleware_chain", [])
        request.state.middleware_chain = chain + ["Idempotency"]
        handle = self._timer.start()
        method = request.method.upper()
        if method == "GET" or request.url.path in {"/healthz", "/readyz", "/metrics"} or request.url.path.startswith("/ui/"):
            duration = handle.elapsed()
            self._metrics.observe_idempotency("bypass", duration)
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        ensure_no_control_chars([key or ""])
        key = normalize_token(key)
        if not key:
            duration = handle.elapsed()
            self._metrics.observe_idempotency("reject", duration)
            return JSONResponse(
                status_code=400,
                content={
                    "fa_error_envelope": {
                        "code": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": "کلید ایدمپوتنسی الزامی است.",
                    }
                },
            )
        namespaced_key = f"idem:{key}"
        try:
            cached = await self._with_retry(
                request,
                op="idempotency.get",
                func=lambda: self._store.get(namespaced_key),
            )
        except RetryExhaustedError as exc:
            return self._retry_failure(request, handle, exc, namespace=namespaced_key)
        if cached:
            payload = decode_response(cached)
            headers = payload.get("headers", {})
            body = payload.get("body", "")
            status = payload.get("status", 200)
            media_type = payload.get("media_type", "application/json")
            duration = handle.elapsed()
            self._metrics.observe_idempotency("hit", duration)
            self._metrics.observe_idempotency_replay()
            diagnostics = getattr(request.app.state, "diagnostics", None)
            if diagnostics and diagnostics.get("enabled"):
                diagnostics["last_idempotency"] = {"outcome": "hit", "duration": duration}
            return Response(content=body, status_code=status, headers=headers, media_type=media_type)

        try:
            stored = await self._with_retry(
                request,
                op="idempotency.set_if_not_exists",
                func=lambda: self._store.set_if_not_exists(
                    namespaced_key,
                    encode_response({"status": 425, "body": "processing"}),
                    self.IDEMPOTENCY_TTL_SECONDS,
                ),
            )
        except RetryExhaustedError as exc:
            return self._retry_failure(request, handle, exc, namespace=namespaced_key)
        if not stored:
            try:
                cached = await self._with_retry(
                    request,
                    op="idempotency.get",
                    func=lambda: self._store.get(namespaced_key),
                )
            except RetryExhaustedError as exc:
                return self._retry_failure(request, handle, exc, namespace=namespaced_key)
            if cached:
                payload = decode_response(cached)
                duration = handle.elapsed()
                self._metrics.observe_idempotency("hit", duration)
                self._metrics.observe_idempotency_replay()
                diagnostics = getattr(request.app.state, "diagnostics", None)
                if diagnostics and diagnostics.get("enabled"):
                    diagnostics["last_idempotency"] = {"outcome": "hit", "duration": duration}
                return Response(
                    content=payload.get("body", ""),
                    status_code=payload.get("status", 200),
                    headers=payload.get("headers", {}),
                    media_type=payload.get("media_type", "application/json"),
                )

        response = await call_next(request)
        body_bytes = b""
        iterator = getattr(response, "body_iterator", None)
        if iterator is not None:
            async for chunk in iterator:
                body_bytes += chunk
        elif getattr(response, "body", None) is not None:
            body_bytes = response.body
        response.body_iterator = iterate_in_threadpool([body_bytes])
        body_payload: str
        if isinstance(body_bytes, bytes):
            body_payload = body_bytes.decode("utf-8")
        elif body_bytes is None:
            body_payload = ""
        else:
            body_payload = str(body_bytes)
        payload = {
            "status": response.status_code,
            "headers": {k: v for k, v in response.headers.items() if k.lower().startswith("x-")},
            "body": body_payload,
            "media_type": response.media_type or "application/json",
        }
        try:
            await self._with_retry(
                request,
                op="idempotency.set",
                func=lambda: self._store.set(
                    namespaced_key,
                    encode_response(payload),
                    self.IDEMPOTENCY_TTL_SECONDS,
                ),
            )
        except RetryExhaustedError as exc:
            return self._retry_failure(request, handle, exc, namespace=namespaced_key)
        duration = handle.elapsed()
        self._metrics.observe_idempotency("miss", duration)
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_idempotency"] = {"outcome": "miss", "duration": duration}
        return response

    async def _with_retry(self, request: Request, *, op: str, func: Callable[[], Awaitable[Any]]) -> Any:
        correlation_id = getattr(request.state, "correlation_id", "idempotency-missing")
        return await execute_with_retry_async(
            func,
            policy=self._retry_policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=self._retryable,
            correlation_id=correlation_id,
            op=op,
        )

    def _retry_failure(self, request: Request, handle, exc: RetryExhaustedError, *, namespace: str) -> Response:
        duration = handle.elapsed()
        self._metrics.observe_idempotency("error", duration)
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_idempotency"] = {
                "outcome": "error",
                "duration": duration,
                "last_error": str(exc.last_error),
            }
        logger.error(
            "idempotency.retry_exhausted",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", None),
                "op": exc.op,
                "namespace": namespace,
                "last_error": str(exc.last_error),
                "retry_attempts": self._retry_policy.max_attempts,
            },
        )
        return JSONResponse(
            status_code=503,
            content={
                "fa_error_envelope": {
                    "code": "RETRY_EXHAUSTED",
                    "message": "در حال حاضر امکان انجام عملیات نیست؛ لطفاً بعداً دوباره تلاش کنید.",
                }
            },
        )


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        token_registry: TokenRegistry,
        metrics: MiddlewareMetrics,
        timer: Timer,
        service_metrics: ServiceMetrics,
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._tokens = token_registry
        self._metrics = metrics
        self._timer = timer
        self._service_metrics = service_metrics

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.middleware_chain = getattr(request.state, "middleware_chain", []) + ["Auth"]
        handle = self._timer.start()
        if request.url.path in {"/healthz", "/readyz", "/download"}:
            duration = handle.elapsed()
            self._metrics.observe_auth(duration)
            return await call_next(request)

        raw_auth = request.headers.get("Authorization")
        header = normalize_token(raw_auth)
        metrics_header = normalize_token(request.headers.get("X-Metrics-Token"))
        ensure_no_control_chars([header or "", metrics_header or ""])
        token_value = ""
        allow_metrics = request.url.path == "/metrics"
        if allow_metrics and metrics_header:
            token_value = metrics_header
        elif header.startswith("Bearer "):
            token_value = header.split(" ", 1)[1].strip()

        try:
            actor = self._tokens.authenticate(token_value, allow_metrics=allow_metrics)
        except AuthorizationError as exc:
            duration = handle.elapsed()
            self._metrics.observe_auth(duration)
            self._service_metrics.auth_fail_total.labels(reason=exc.reason).inc()
            diagnostics = getattr(request.app.state, "diagnostics", None)
            if diagnostics and diagnostics.get("enabled"):
                diagnostics["last_auth"] = {"duration": duration, "authorized": False, "reason": exc.reason}
            logger.warning(
                "auth.failed",
                extra={
                    "correlation_id": getattr(request.state, "correlation_id", None),
                    "reason": exc.reason,
                },
            )
            status = 401 if exc.reason != "scope_denied" else 403
            return JSONResponse(
                status_code=status,
                content={
                    "fa_error_envelope": {
                        "code": "UNAUTHORIZED",
                        "message": exc.message_fa,
                    }
                },
            )

        request.state.actor = actor
        response = await call_next(request)
        duration = handle.elapsed()
        self._metrics.observe_auth(duration)
        self._service_metrics.auth_ok_total.labels(role=actor.role).inc()
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_auth"] = {"duration": duration, "authorized": True, "role": actor.role}
        logger.info(
            "auth.ok",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", None),
                "role": actor.role,
                "metrics_only": actor.metrics_only,
                "fingerprint": actor.token_fingerprint,
            },
        )
        return response


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
        diagnostics = getattr(request.app.state, "diagnostics", None)
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_chain"] = getattr(request.state, "middleware_chain", [])
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
        diagnostics = self._diagnostics_factory()
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_chain"] = getattr(request.state, "middleware_chain", [])
        return response


__all__ = [
    "CorrelationIdMiddleware",
    "RateLimitMiddleware",
    "IdempotencyMiddleware",
    "AuthMiddleware",
    "MetricsMiddleware",
    "RequestLoggingMiddleware",
]
