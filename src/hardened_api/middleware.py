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

from .observability import (
    StructuredLogger,
    emit_log,
    get_metric,
    hash_national_id,
    mask_phone,
)
from .redis_support import (
    IdempotencyConflictError,
    RedisIdempotencyRepository,
    RedisNamespaces,
    RedisSlidingWindowLimiter,
    RedisOperationError,
    JWTDenyList,
)


class APIKeyRepository(Protocol):
    async def is_active(self, hashed_key: str) -> bool: ...

_ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$")


@dataclass(slots=True)
class AuthConfig:
    bearer_secret: str | None
    api_key_salt: str
    accepted_audience: set[str]
    accepted_issuers: set[str]
    allow_plain_tokens: set[str]
    api_key_repository: "APIKeyRepository"
    jwt_deny_list: JWTDenyList | None = None


@dataclass(slots=True)
class RateLimitRule:
    requests: int
    window_seconds: float


@dataclass(slots=True)
class RateLimitConfig:
    default_rule: RateLimitRule
    per_route: dict[str, RateLimitRule]
    fail_open: bool = False


@dataclass(frozen=True)
class RateLimitRuleSnapshot:
    requests: int
    window_seconds: float


@dataclass(frozen=True)
class RateLimitConfigSnapshot:
    default: RateLimitRuleSnapshot
    per_route: tuple[tuple[str, RateLimitRuleSnapshot], ...]
    fail_open: bool


def snapshot_rate_limit_config(config: RateLimitConfig) -> RateLimitConfigSnapshot:
    return RateLimitConfigSnapshot(
        default=RateLimitRuleSnapshot(
            requests=config.default_rule.requests,
            window_seconds=config.default_rule.window_seconds,
        ),
        per_route=tuple(
            sorted(
                (
                    route,
                    RateLimitRuleSnapshot(
                        requests=rule.requests,
                        window_seconds=rule.window_seconds,
                    ),
                )
                for route, rule in config.per_route.items()
            )
        ),
        fail_open=config.fail_open,
    )


def restore_rate_limit_config(config: RateLimitConfig, snapshot: RateLimitConfigSnapshot) -> None:
    config.default_rule.requests = snapshot.default.requests
    config.default_rule.window_seconds = snapshot.default.window_seconds
    config.fail_open = snapshot.fail_open

    desired_routes = {route for route, _ in snapshot.per_route}
    for route in list(config.per_route.keys()):
        if route not in desired_routes:
            config.per_route.pop(route)

    for route, rule_snapshot in snapshot.per_route:
        existing = config.per_route.get(route)
        if existing is None:
            config.per_route[route] = RateLimitRule(
                requests=rule_snapshot.requests,
                window_seconds=rule_snapshot.window_seconds,
            )
            continue
        existing.requests = rule_snapshot.requests
        existing.window_seconds = rule_snapshot.window_seconds


def ensure_rate_limit_config_restored(
    config: RateLimitConfig,
    snapshot: RateLimitConfigSnapshot,
    *,
    context: str | None = None,
) -> None:
    if snapshot_rate_limit_config(config) != snapshot:
        restore_rate_limit_config(config, snapshot)
        suffix = f" ({context})" if context else ""
        raise AssertionError(
            "Rate limit configuration mutated outside guarded scope" + suffix
        )


@contextmanager
def rate_limit_config_guard(config: RateLimitConfig) -> Iterator[RateLimitConfig]:
    snapshot = snapshot_rate_limit_config(config)
    try:
        yield config
    finally:
        restore_rate_limit_config(config, snapshot)


@dataclass(slots=True)
class MiddlewareState:
    logger: StructuredLogger
    auth_config: AuthConfig
    rate_limit_config: RateLimitConfig
    metrics_token: str | None
    metrics_ip_allowlist: set[str]
    max_body_bytes: int
    namespaces: RedisNamespaces
    rate_limiter: RedisSlidingWindowLimiter
    idempotency_repository: RedisIdempotencyRepository


def get_rate_limit_info() -> dict[str, Any]:
    return {"mode": "redis"}


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


async def _parse_jwt(token: str) -> dict[str, Any]:
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(_pad_b64(header_b64)))
    payload = json.loads(base64.urlsafe_b64decode(_pad_b64(payload_b64)))
    signature = base64.urlsafe_b64decode(_pad_b64(signature_b64))
    return {"header": header, "payload": payload, "signature": signature}


def _pad_b64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return padded.encode("utf-8")


async def _validate_jwt(
    token: str,
    *,
    secret: str,
    leeway: int,
    audience: set[str],
    issuers: set[str],
    deny_list: JWTDenyList,
    correlation_id: str,
) -> tuple[str, dict[str, Any]]:
    import hashlib
    import hmac

    parts = await _parse_jwt(token)
    header = parts["header"]
    payload = parts["payload"]
    if header.get("alg") != "HS256":
        raise ValueError("ALG_UNSUPPORTED|الگوریتم امضا پشتیبانی نمی‌شود")
    signing_input = ".".join(token.split(".")[:2]).encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, parts["signature"]):
        raise ValueError("SIGNATURE_INVALID|امضای توکن نامعتبر است")
    now = int(time.time())
    exp = int(payload.get("exp", 0))
    if exp and now > exp + leeway:
        raise ValueError("TOKEN_EXPIRED|توکن منقضی شده است")
    iat = int(payload.get("iat", 0))
    if iat and now + leeway < iat:
        raise ValueError("TOKEN_IAT_INVALID|زمان انتشار معتبر نیست")
    aud = payload.get("aud")
    if audience and aud not in audience:
        raise ValueError("AUD_INVALID|شناسه سرویس مجاز نیست")
    iss = payload.get("iss")
    if issuers and iss not in issuers:
        raise ValueError("ISSUER_INVALID|صادرکننده مجاز نیست")
    subject = payload.get("sub")
    if not subject:
        raise ValueError("SUBJECT_MISSING|شناسه کاربر موجود نیست")
    jti = payload.get("jti")
    if jti and await deny_list.is_revoked(str(jti), correlation_id=correlation_id):
        raise ValueError("TOKEN_REVOKED|توکن باطل شده است")
    return str(subject), payload


async def authenticate_request(
    request: Request,
    config: AuthConfig,
) -> tuple[str, str]:
    header = request.headers.get("Authorization")
    api_key = request.headers.get("X-API-Key")
    if not header and not api_key:
        raise PermissionError("AUTH_REQUIRED|احراز هویت لازم است")
    if api_key:
        if not _ASCII_TOKEN_RE.fullmatch(api_key):
            raise PermissionError("INVALID_TOKEN|کلید API نامعتبر است")
        hashed = hash_national_id(api_key, salt=config.api_key_salt)
        if not await config.api_key_repository.is_active(hashed):
            raise PermissionError("INVALID_TOKEN|کلید API مجاز نیست")
        return hashed, "api_key"
    if not header.startswith("Bearer "):
        raise PermissionError("INVALID_TOKEN|قالب هدر Authorization نامعتبر است")
    token = header[7:]
    if not _ASCII_TOKEN_RE.fullmatch(token):
        raise PermissionError("INVALID_TOKEN|توکن مجاز نیست")
    if token in config.allow_plain_tokens:
        return token, "bearer"
    if config.bearer_secret:
        if config.jwt_deny_list is None:
            raise PermissionError("INVALID_TOKEN|پیکربندی JWT ناقص است")
        subject, _payload = await _validate_jwt(
            token,
            secret=config.bearer_secret,
            leeway=120,
            audience=config.accepted_audience,
            issuers=config.accepted_issuers,
            deny_list=config.jwt_deny_list,
            correlation_id=getattr(request.state, "correlation_id", "-"),
        )
        return subject, "jwt"
    raise PermissionError("INVALID_TOKEN|توکن پشتیبانی نمی‌شود")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.correlation_id = derive_correlation_id(request)
        request.state.request_id = request.headers.get("X-Request-ID")
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, state: MiddlewareState) -> None:
        super().__init__(app)
        self._state = state

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        consumer = getattr(request.state, "consumer_id", None)
        if not consumer:
            api_key = request.headers.get("X-API-Key")
            if api_key and _ASCII_TOKEN_RE.fullmatch(api_key):
                consumer = hash_national_id(api_key, salt=self._state.auth_config.api_key_salt)
            else:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer ") and _ASCII_TOKEN_RE.fullmatch(auth_header[7:]):
                    consumer = hash_national_id(auth_header[7:], salt=self._state.auth_config.api_key_salt)
        if not consumer:
            consumer = request.client.host if request.client else "anonymous"
        route = request.url.path
        rule = self._state.rate_limit_config.per_route.get(route, self._state.rate_limit_config.default_rule)
        limiter = self._state.rate_limiter
        try:
            result = await limiter.allow(
                consumer,
                route,
                requests=rule.requests,
                window_seconds=rule.window_seconds,
                correlation_id=getattr(request.state, "correlation_id", "-"),
            )
        except RedisOperationError as exc:
            if self._state.rate_limit_config.fail_open or request.method == "GET":
                request.state.rate_limit_remaining = rule.requests
                return await call_next(request)
            raise ValueError("INTERNAL|سامانهٔ محدودکنندهٔ درخواست در دسترس نیست") from exc
        else:
            if not result.allowed:
                get_metric("rate_limit_reject_total").labels(route=route).inc()
                retry_after = result.retry_after or rule.window_seconds
                request.state.retry_after = max(1, int(math.ceil(retry_after)))
                request.state.rate_limit_remaining = 0
                raise ValueError("RATE_LIMIT_EXCEEDED|تعداد درخواست‌ها از حد مجاز فراتر رفته است")
            request.state.rate_limit_remaining = result.remaining
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, state: MiddlewareState) -> None:
        super().__init__(app)
        self._state = state

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method != "POST" or request.url.path != "/allocations":
            return await call_next(request)
        header = request.headers.get("Idempotency-Key")
        if not header:
            return await call_next(request)
        if not _ASCII_TOKEN_RE.fullmatch(header):
            raise ValueError("VALIDATION_ERROR|کلید تکرارناپذیری نامعتبر است")
        body = getattr(request, "_body", None)
        if body is None:
            body = await request.body()
        try:
            parsed = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            raise ValueError("VALIDATION_ERROR|payload نامعتبر است") from exc
        body_hash = hash_national_id(json.dumps(parsed, sort_keys=True, ensure_ascii=False), salt=self._state.auth_config.api_key_salt)
        try:
            reservation, cached = await self._state.idempotency_repository.reserve(
                header,
                body_hash,
                correlation_id=getattr(request.state, "correlation_id", "-"),
            )
        except IdempotencyConflictError as exc:
            raise ValueError("CONFLICT|درخواست تکراری با بدنهٔ متفاوت") from exc
        request.state.idempotency_key = header
        request.state.idempotency_reservation = reservation
        if cached is not None:
            response = Response(
                content=json.dumps(cached, ensure_ascii=False),
                media_type="application/json",
                status_code=200,
            )
            request.state.idempotency_cached = cached
            return response
        try:
            response = await call_next(request)
        except Exception:
            reservation = getattr(request.state, "idempotency_reservation", None)
            if reservation:
                await reservation.abort()
            raise
        return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, state: MiddlewareState) -> None:
        super().__init__(app)
        self._state = state

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            consumer_id, scheme = await authenticate_request(request, self._state.auth_config)
        except PermissionError as exc:  # mapped upstream
            get_metric("auth_fail_total").labels(reason=str(exc)).inc()
            raise
        request.state.consumer_id = consumer_id
        request.state.auth_scheme = scheme
        return await call_next(request)


def setup_middlewares(app: ASGIApp, *, state: MiddlewareState, allowed_origins: Iterable[str]) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["POST", "GET"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Correlation-ID", "Retry-After", "X-RateLimit-Remaining"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RateLimitMiddleware, state=state)
    app.add_middleware(IdempotencyMiddleware, state=state)
    app.add_middleware(AuthenticationMiddleware, state=state)


async def finalize_response(
    request: Request,
    response: Response,
    *,
    logger: StructuredLogger,
    status_code: int,
    error_code: str | None = None,
    outcome: str,
) -> None:
    consumer_id = getattr(request.state, "consumer_id", "anonymous")
    correlation_id = getattr(request.state, "correlation_id", "-")
    request_id = getattr(request.state, "request_id", None)
    duration_ms = (time.perf_counter() - getattr(request.state, "_start_time", time.perf_counter())) * 1000
    emit_log(
        logger=logger,
        level="INFO" if status_code < 400 else "WARNING",
        msg="request.completed",
        correlation_id=correlation_id,
        request_id=request_id,
        consumer_id=consumer_id,
        path=request.url.path,
        method=request.method,
        status=status_code,
        latency_ms=duration_ms,
        outcome=outcome,
        error_code=error_code,
        extra={},
    )
    if consumer_id.startswith("09"):
        request.state.consumer_id = mask_phone(consumer_id)


def get_client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return os.getenv("GITHUB_RUNNER_IP", "127.0.0.1")
