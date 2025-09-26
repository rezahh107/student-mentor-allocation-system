"""Hardened API middleware components."""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import math
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.concurrency import iterate_in_threadpool

from .observability import (
    Observability,
    get_correlation_id,
    get_consumer_id,
    set_consumer_id,
    set_correlation_id,
    set_request_id,
)
from .patterns import ascii_token_pattern, zero_width_pattern
from .idempotency_store import (
    IdempotencyConflictError,
    IdempotencyDegradedError,
    IdempotencyLock,
    IdempotencyLockTimeoutError,
    IdempotencyRecord,
    IdempotencyStore,
)
from .rate_limit_backends import RateLimitBackend, RateLimitDecision, redis_key
from .security_hardening import validate_jwt_claims

ASCII_TOKEN = ascii_token_pattern(512)
ZERO_WIDTH_RE = zero_width_pattern()


@dataclass(slots=True)
class StaticCredential:
    """Represents an in-memory credential (Bearer token)."""

    token: str
    scopes: frozenset[str]
    consumer_id: str


@dataclass(slots=True)
class AuthenticationConfig:
    """Configuration for the authentication middleware."""

    static_credentials: dict[str, StaticCredential]
    jwt_secret: str | None
    leeway_seconds: int = 120
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    required_scopes: dict[str, set[str]] | None = None
    public_paths: set[str] = field(default_factory=set)


class APIKeyInfo(Protocol):
    """Information returned by API key providers."""

    consumer_id: str
    scopes: set[str]
    name: str | None
    expires_at: datetime | None
    is_active: bool


class APIKeyProvider(Protocol):
    """Provider used for API key validation."""

    async def verify(self, value: str) -> APIKeyInfo | None:  # pragma: no cover - interface
        ...


def install_cors(app: ASGIApp, *, allow_origins: Iterable[str]) -> None:
    """Attach a strict CORS middleware to the ASGI app."""

    if isinstance(app, FastAPI):  # type: ignore[name-defined]
        target = app
    else:
        target = app
    target.add_middleware(  # type: ignore[call-arg]
        CORSMiddleware,
        allow_origins=list(allow_origins),
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-API-Key",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
        expose_headers=["X-Correlation-ID", "X-RateLimit-Remaining"],
        allow_credentials=False,
        max_age=600,
    )


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensures a correlation identifier exists for every request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        raw_request_id = request.headers.get("X-Request-ID") or ""
        clean_request_id = _sanitize_header_token(raw_request_id)
        if not clean_request_id:
            clean_request_id = str(uuid4())
        set_request_id(clean_request_id)

        raw_correlation = request.headers.get("X-Correlation-ID") or clean_request_id
        correlation_id = _sanitize_header_token(raw_correlation) or clean_request_id
        set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        request.state.request_id = clean_request_id

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def _match_path(paths: tuple[str, ...], target: str) -> bool:
    if not paths:
        return True
    return any(target == candidate or target.startswith(f"{candidate}/") for candidate in paths)

def _distributed_backoff(attempt: int, key: str, *, base: float = 0.01, ceiling: float = 0.3) -> float:
    """Deterministic jittered backoff for distributed locks."""
    growth = base * (2 ** max(0, attempt - 1))
    jitter_seed = hash((key, attempt)) & 0xFFFF
    jitter = (jitter_seed % max(1, int(base * 1000))) / 1000.0
    return min(growth + jitter, ceiling)



async def _send_validation_response(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    details: list[dict[str, Any]],
    message: str,
) -> None:
    correlation_id = get_correlation_id()
    payload: dict[str, Any] = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message_fa": message,
            "correlation_id": correlation_id,
        }
    }
    if details:
        payload["details"] = details
    headers = {"X-Correlation-ID": correlation_id, "X-Error-Code": "VALIDATION_ERROR"}
    scope.setdefault("state", {})["error_code"] = "VALIDATION_ERROR"
    response = JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload, headers=headers)
    await response(scope, receive, send)


def _decode_header(headers: list[tuple[bytes, bytes]], name: str) -> str:
    needle = name.lower()
    for key, value in headers:
        if key.decode("latin-1").lower() == needle:
            return value.decode("latin-1").strip()
    return ""


async def _drain_request_body(receive: Receive, initial: Message | None = None) -> None:
    more_body = False
    if initial is not None:
        more_body = bool(initial.get("more_body"))
    while more_body:
        message = await receive()
        if message.get("type") != "http.request":
            more_body = bool(message.get("more_body"))
            continue
        more_body = bool(message.get("more_body"))


class ContentTypeValidationMiddleware:
    """Reject requests that do not use the required JSON content type."""

    def __init__(self, app: ASGIApp, *, methods: Iterable[str], paths: Iterable[str] | None = None) -> None:
        self.app = app
        self._methods = {method.upper() for method in methods}
        self._paths = tuple(paths or ())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        if method not in self._methods:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _match_path(self._paths, path):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or []
        content_type = _decode_header(list(headers), "content-type").lower()
        if content_type != "application/json; charset=utf-8":
            details = [
                {
                    "loc": ["header", "Content-Type"],
                    "msg": "نوع محتوا باید application/json; charset=utf-8 باشد",
                    "type": "value_error.content_type",
                }
            ]
            await _send_validation_response(
                scope,
                receive,
                send,
                details=details,
                message="درخواست نامعتبر است",
            )
            return

        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Ensure request bodies stay within the configured byte limit."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit_bytes: int,
        methods: Iterable[str],
        paths: Iterable[str] | None = None,
    ) -> None:
        self.app = app
        self._limit = limit_bytes
        self._methods = {method.upper() for method in methods}
        self._paths = tuple(paths or ())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        if method not in self._methods:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _match_path(self._paths, path):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        buffered: list[Message] = []
        tail: list[Message] = []

        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type != "http.request":
                tail.append(message)
                if not message.get("more_body", False):
                    break
                continue

            chunk = message.get("body", b"") or b""
            more_body = bool(message.get("more_body", False))
            if chunk:
                body.extend(chunk)
                if len(body) > self._limit:
                    await _drain_request_body(receive, message)
                    details = [
                        {
                            "loc": ["body"],
                            "msg": "حجم بدنهٔ درخواست بیش از حد مجاز است",
                            "type": "value_error.body_size",
                            "ctx": {"limit": self._limit},
                        }
                    ]
                    await _send_validation_response(
                        scope,
                        receive,
                        send,
                        details=details,
                        message="درخواست نامعتبر است",
                    )
                    return

            buffered.append({"type": "http.request", "body": chunk, "more_body": more_body})
            if not more_body:
                break

        body_bytes = bytes(body)
        scope_state = scope.setdefault("state", {})
        scope_state["raw_body"] = body_bytes

        if not buffered:
            buffered.append({"type": "http.request", "body": body_bytes, "more_body": False})

        replay_messages = buffered + tail
        index = 0

        async def replay_receive() -> Message:
            nonlocal index
            if index < len(replay_messages):
                message = replay_messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Applies standard security headers on all responses."""

    def __init__(self, app: ASGIApp, *, allow_origins: Iterable[str]) -> None:
        super().__init__(app)
        self._allow_origins = set(allow_origins)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        origin = request.headers.get("Origin")
        if origin and origin in self._allow_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Performs authentication and populates consumer context."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: AuthenticationConfig,
        observability: Observability,
        api_key_provider: APIKeyProvider | None = None,
    ) -> None:
        super().__init__(app)
        self._config = config
        self._observability = observability
        self._api_key_provider = api_key_provider

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if any(path == pub or path.startswith(f"{pub}/") for pub in self._config.public_paths):
            return await call_next(request)
        auth_header = request.headers.get("Authorization") or ""
        api_key_value = request.headers.get("X-API-Key") or ""

        if not auth_header and not api_key_value:
            self._observability.increment_auth_failure("missing")
            return build_error_response(
                HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "AUTH_REQUIRED", "message_fa": "توکن احراز هویت الزامی است"},
                )
            )

        context = None
        if api_key_value:
            context = await self._handle_api_key(api_key_value)
        elif auth_header:
            context = await self._handle_authorization(auth_header)

        if context is None:
            self._observability.increment_auth_failure("invalid")
            return build_error_response(
                HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "INVALID_TOKEN", "message_fa": "اعتبارسنجی توکن انجام نشد"},
                )
            )

        required = self._config.required_scopes or {}
        route_scopes = required.get(request.url.path) or required.get(request.scope.get("path", ""))
        if route_scopes and not route_scopes.issubset(context.scopes):
            self._observability.increment_auth_failure("forbidden")
            return build_error_response(
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "ROLE_DENIED", "message_fa": "دسترسی لازم وجود ندارد"},
                )
            )

        set_consumer_id(context.consumer_id)
        request.state.auth_context = context
        request.state.consumer_id = context.consumer_id
        response = await call_next(request)
        return response

    async def _handle_api_key(self, api_key_value: str) -> AuthContext | None:
        clean_value = _sanitize_header_token(api_key_value)
        if not clean_value or not ASCII_TOKEN.fullmatch(clean_value):
            return None
        if self._api_key_provider is None:
            return None
        info = await self._api_key_provider.verify(clean_value)
        if info is None or not info.is_active:
            return None
        if info.expires_at and info.expires_at <= datetime.now(timezone.utc):
            return None
        consumer_id = info.consumer_id
        scopes = info.scopes
        return AuthContext(token_type="api_key", consumer_id=consumer_id, scopes=scopes, subject=info.name or "api")

    async def _handle_authorization(self, header: str) -> AuthContext | None:
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        clean_token = _sanitize_header_token(token)
        if not clean_token or not ASCII_TOKEN.fullmatch(clean_token):
            return None
        if clean_token in self._config.static_credentials:
            cred = self._config.static_credentials[clean_token]
            return AuthContext(token_type="bearer", consumer_id=cred.consumer_id, scopes=set(cred.scopes), subject=cred.consumer_id)
        if self._config.jwt_secret is None:
            return None
        try:
            payload = _decode_jwt(clean_token, secret=self._config.jwt_secret, leeway=self._config.leeway_seconds)
            validate_jwt_claims(
                payload,
                issuer=self._config.jwt_issuer,
                audience=self._config.jwt_audience,
            )
        except (JWTValidationError, ValueError):
            return None
        scopes_raw = payload.get("scopes") or payload.get("scope") or ""
        if isinstance(scopes_raw, str):
            scopes = {s for s in scopes_raw.split() if s}
        elif isinstance(scopes_raw, list):
            scopes = {str(s) for s in scopes_raw}
        else:
            scopes = set()
        subject = str(payload.get("sub") or payload.get("client_id") or "jwt")
        consumer_id = _hash_consumer_id(clean_token)
        return AuthContext(token_type="jwt", consumer_id=consumer_id, scopes=scopes, subject=subject)


@dataclass(slots=True)
class AuthContext:
    """Authentication context stored on the request state."""

    token_type: str
    consumer_id: str
    scopes: set[str]
    subject: str



class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Caches idempotent responses and short-circuits replays."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: IdempotencyStore,
        ttl_seconds: int,
        observability: Observability,
        paths: Iterable[str] | None = None,
        compress_min_bytes: int = 16_384,
        max_cache_bytes: int = 1_000_000,
    ) -> None:
        super().__init__(app)
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._observability = observability
        self._paths = tuple(paths or ())
        self._lock_ttl_ms = 5_000
        self._compress_min_bytes = max(0, int(compress_min_bytes))
        self._max_cache_bytes = max(1, int(max_cache_bytes))

    def _path_allowed(self, path: str) -> bool:
        if not self._paths:
            return True
        return any(path == candidate or path.startswith(f"{candidate}/") for candidate in self._paths)
    def _degraded_response(self, message: str) -> JSONResponse:
        self._observability.increment_idempotency("degraded")
        detail = {"code": "DEGRADED_MODE", "message_fa": message}
        exc = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            headers={"Retry-After": "1", "X-Degraded-Mode": "true"},
        )
        return build_error_response(exc)


    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.idempotency_key = None
        request.state.idempotency_body_hash = None
        request.state.idempotency_replay = False

        if request.method.upper() != "POST" or not self._path_allowed(request.url.path):
            return await call_next(request)

        raw_key = request.headers.get("Idempotency-Key")
        if not raw_key:
            return await call_next(request)

        clean_key = _sanitize_header_token(raw_key)
        if not clean_key or not ASCII_TOKEN.fullmatch(clean_key):
            detail = [
                {
                    "loc": ["header", "Idempotency-Key"],
                    "msg": "قالب Idempotency-Key نامعتبر است",
                    "type": "value_error.header.idempotency_key",
                }
            ]
            return build_error_response(
                    HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "VALIDATION_ERROR",
                        "message_fa": "درخواست نامعتبر است",
                        "details": detail,
                    },
                )
            )

        cache_scope = request.scope.get("path", request.url.path)
        cache_key = f"{request.method.upper()}:{cache_scope}:{clean_key}"
        request.state.idempotency_key = clean_key
        request.state.idempotency_cache_key = cache_key
        body = getattr(request.state, "raw_body", None)
        if body is None:
            body = await request.body()
            request.state.raw_body = body
        body_hash = _hash_body(body)
        request.state.idempotency_body_hash = body_hash

        attempts = 0
        lock: IdempotencyLock | None = None
        while True:
            try:
                record = await self._store.get(cache_key, body_hash=body_hash, ttl_seconds=self._ttl_seconds)
            except IdempotencyConflictError:
                self._observability.increment_idempotency("conflict")
                request.state.error_code = "CONFLICT"
                return build_error_response(
                    HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "CONFLICT", "message_fa": "کلید ایدمپوتنسی با بدنهٔ متفاوت تکرار شده است"},
                    )
                )
            except IdempotencyDegradedError:
                self._observability.increment_idempotency_degraded("get")
                request.state.error_code = "DEGRADED_MODE"
                return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")

            if record is not None:
                self._observability.increment_idempotency("replay")
                request.state.idempotency_replay = True
                start_replay = time.perf_counter()
                payload_bytes = record.payload
                if record.is_compressed:
                    try:
                        payload_bytes = gzip.decompress(payload_bytes)
                    except OSError:
                        self._observability.increment_idempotency_degraded("replay-decompress")
                        request.state.error_code = "DEGRADED_MODE"
                        return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")
                replay_duration = time.perf_counter() - start_replay
                self._observability.observe_idempotency_replay(
                    payload_bytes=len(payload_bytes),
                    compressed=record.is_compressed,
                    duration_seconds=replay_duration,
                )
                headers = dict(record.headers)
                headers.pop("X-Idempotency-Lock", None)
                headers.setdefault("X-Correlation-ID", get_correlation_id())
                headers["X-Idempotent-Replay"] = "true"
                media_type = record.content_type or "application/json"
                return Response(
                    content=payload_bytes,
                    status_code=record.status_code,
                    headers=headers,
                    media_type=media_type,
                )

            if lock is None:
                try:
                    lock = await self._store.acquire_lock(cache_key, ttl_ms=self._lock_ttl_ms)
                    break
                except IdempotencyLockTimeoutError:
                    attempts += 1
                    self._observability.increment_idempotency_lock_contention("timeout")
                    if attempts >= 5:
                        self._observability.increment_idempotency_degraded("lock-timeout")
                        request.state.error_code = "DEGRADED_MODE"
                        return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")
                    await asyncio.sleep(_distributed_backoff(attempts, cache_key))
                    continue
                except IdempotencyDegradedError:
                    self._observability.increment_idempotency_degraded("lock")
                    request.state.error_code = "DEGRADED_MODE"
                    return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")

        if lock is None:
            return await call_next(request)

        async with lock:
            try:
                record = await self._store.get(cache_key, body_hash=body_hash, ttl_seconds=self._ttl_seconds)
            except IdempotencyConflictError:
                self._observability.increment_idempotency("conflict")
                request.state.error_code = "CONFLICT"
                return build_error_response(
                    HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "CONFLICT", "message_fa": "کلید ایدمپوتنسی با بدنهٔ متفاوت تکرار شده است"},
                    )
                )
            except IdempotencyDegradedError:
                self._observability.increment_idempotency_degraded("get")
                request.state.error_code = "DEGRADED_MODE"
                return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")

            if record is not None:
                self._observability.increment_idempotency("replay")
                request.state.idempotency_replay = True
                start_replay = time.perf_counter()
                payload_bytes = record.payload
                if record.is_compressed:
                    try:
                        payload_bytes = gzip.decompress(payload_bytes)
                    except OSError:
                        self._observability.increment_idempotency_degraded("replay-decompress")
                        request.state.error_code = "DEGRADED_MODE"
                        return self._degraded_response("سامانه موقتاً در حالت کاهش کیفیت قرار دارد")
                replay_duration = time.perf_counter() - start_replay
                self._observability.observe_idempotency_replay(
                    payload_bytes=len(payload_bytes),
                    compressed=record.is_compressed,
                    duration_seconds=replay_duration,
                )
                headers = dict(record.headers)
                headers.pop("X-Idempotency-Lock", None)
                headers.setdefault("X-Correlation-ID", get_correlation_id())
                headers["X-Idempotent-Replay"] = "true"
                media_type = record.content_type or "application/json"
                return Response(
                    content=payload_bytes,
                    status_code=record.status_code,
                    headers=headers,
                    media_type=media_type,
                )

            self._observability.increment_idempotency("miss")
            response = await call_next(request)
            override = await self._store_response(cache_key, body_hash, response, lock)
            if override is not None:
                request.state.error_code = "DEGRADED_MODE"
                return override
            return response


    async def _store_response(
        self,
        key: str,
        body_hash: str,
        response: Response,
        lock: IdempotencyLock | None,
    ) -> Response | None:
        if not key or not body_hash:
            return None
        if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            return None
        media_type = (response.media_type or response.headers.get("content-type") or "").lower()
        if "json" not in media_type:
            return None

        start = time.perf_counter()
        body_iterator = getattr(response, "body_iterator", None)
        buffer = bytearray()
        self._observability.track_idempotency_buffer(0)
        try:
            if body_iterator is not None:
                async for chunk in body_iterator:
                    if isinstance(chunk, (bytes, bytearray)):
                        buffer.extend(chunk)
                    else:
                        buffer.extend(str(chunk).encode("utf-8"))
                    current = len(buffer)
                    self._observability.track_idempotency_buffer(current)
                    if current > self._max_cache_bytes:
                        self._observability.increment_idempotency_degraded("cache-too-large")
                        return self._degraded_response("حجم پاسخ از حد مجاز سامانه فراتر رفت")
                body_bytes = bytes(buffer)
                response.body_iterator = iterate_in_threadpool(iter([body_bytes]))
            else:
                try:
                    raw_body = response.body
                except AttributeError:
                    raw_body = b""
                if isinstance(raw_body, str):
                    body_bytes = raw_body.encode("utf-8")
                elif isinstance(raw_body, (bytes, bytearray)):
                    body_bytes = bytes(raw_body)
                else:
                    body_bytes = b""
                if len(body_bytes) > self._max_cache_bytes:
                    self._observability.increment_idempotency_degraded("cache-too-large")
                    return self._degraded_response("حجم پاسخ از حد مجاز سامانه فراتر رفت")

            if not body_bytes:
                return None

            try:
                json.loads(body_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

            compressed = False
            stored_bytes = body_bytes
            if len(body_bytes) >= self._compress_min_bytes:
                stored_bytes = gzip.compress(body_bytes)
                compressed = True

            duration = time.perf_counter() - start
            self._observability.observe_idempotency_serialization(
                raw_bytes=len(body_bytes),
                stored_bytes=len(stored_bytes),
                compressed=compressed,
                duration_seconds=duration,
            )

            headers = {k: v for k, v in response.headers.items() if k.lower().startswith("x-")}
            headers.setdefault("X-Correlation-ID", get_correlation_id())
            if lock is not None:
                headers["X-Idempotency-Lock"] = lock.token
            record = IdempotencyRecord(
                body_hash=body_hash,
                payload=stored_bytes,
                status_code=response.status_code,
                headers=headers,
                stored_at=time.time(),
                fencing_token=lock.fencing_token if lock is not None else 0,
                is_compressed=compressed,
                content_type=response.headers.get("content-type", response.media_type or "application/json"),
            )
            await self._store.set(
                key,
                record,
                ttl_seconds=self._ttl_seconds,
                fencing_token=lock.fencing_token if lock is not None else None,
            )
            self._observability.increment_idempotency("stored")
            return None
        finally:
            self._observability.track_idempotency_buffer(0)


class RateLimiter:
    """Sliding window limiter delegating to a backend."""

    def __init__(self, *, backend: RateLimitBackend, capacity: int, refill_rate_per_sec: float, namespace: str) -> None:
        self._backend = backend
        self._capacity = capacity
        self._refill_rate = refill_rate_per_sec
        self._namespace = namespace

    def build_key(self, route: str, consumer: str) -> str:
        return redis_key(self._namespace, "rl", route, consumer)

    async def consume(self, route: str, consumer: str) -> RateLimitDecision:
        key = self.build_key(route, consumer)
        return await self._backend.consume(key, capacity=self._capacity, refill_rate_per_sec=self._refill_rate)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies per-consumer rate limiting."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        observability: Observability,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._observability = observability

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        consumer_id = getattr(request.state, "consumer_id", None) or get_consumer_id()
        if not consumer_id:
            consumer_id = request.client.host if request.client and request.client.host else "anonymous"
        request.state.consumer_id = consumer_id
        route = request.scope.get("path", request.url.path)
        decision = await self._limiter.consume(route, consumer_id)
        if not decision.allowed:
            self._observability.increment_rate_limit(route)
            request.state.error_code = "RATE_LIMIT_EXCEEDED"
            retry_after = max(int(math.ceil(decision.retry_after)), 1)
            headers = {
                "Retry-After": str(retry_after),
                "X-RateLimit-Remaining": "0",
            }
            return build_error_response(
                HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={"code": "RATE_LIMIT_EXCEEDED", "message_fa": "تعداد درخواست‌ها بیش از حد مجاز است"},
                    headers=headers,
                )
            )
        response = await call_next(request)
        remaining = max(0, int(math.floor(decision.remaining)))
        response.headers.setdefault("X-RateLimit-Remaining", str(remaining))
        return response


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Captures latency metrics and structured logs."""

    def __init__(self, app: ASGIApp, *, observability: Observability) -> None:
        super().__init__(app)
        self._observability = observability

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        self._observability.http_requests_in_flight.inc()
        start = time.perf_counter()
        status_code = 500
        outcome = "UNKNOWN"
        error_code: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            outcome = "SUCCESS" if 200 <= status_code < 300 else "ERROR"
            if error_code is None:
                header_code = response.headers.get("X-Error-Code")
                if header_code:
                    error_code = header_code
                else:
                    code_hint = getattr(request.state, "error_code", None)
                    if code_hint:
                        error_code = code_hint
            return response
        except HTTPException as exc:
            status_code = exc.status_code
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            error_code = str(detail.get("code") or "ERROR")
            outcome = "ERROR"
            return build_error_response(exc)
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR))
            error_code = str(getattr(exc, "error_code", "ERROR"))
            outcome = "ERROR"
            raise
        finally:
            latency = time.perf_counter() - start
            self._observability.http_requests_in_flight.dec()
            correlation_id = getattr(request.state, "correlation_id", "") or get_correlation_id()
            if correlation_id:
                set_correlation_id(correlation_id)
            request_id = getattr(request.state, "request_id", "") or correlation_id
            if request_id:
                set_request_id(request_id)
            auth_ctx = getattr(request.state, "auth_context", None)
            if auth_ctx is not None and getattr(auth_ctx, "consumer_id", None):
                set_consumer_id(auth_ctx.consumer_id)
            path = request.url.path
            method = request.method
            self._observability.record_request_metrics(path=path, method=method, status=status_code, latency_seconds=latency)
            if latency * 1000 > self._observability.config.latency_budget_ms:
                self._observability.emit(
                    level=logging.WARNING,
                    msg="بودجهٔ تأخیر نقض شد",
                    path=path,
                    method=method,
                    status=status_code,
                    latency_ms=round(latency * 1000, 3),
                )
            if error_code is None:
                code_hint = getattr(request.state, "error_code", None)
                if code_hint:
                    error_code = code_hint
            self._observability.log_request(
                path=path,
                method=method,
                status=status_code,
                latency_ms=latency * 1000,
                outcome=outcome,
                error_code=error_code,
            )


def build_error_response(exc: HTTPException) -> JSONResponse:
    """Convert an HTTPException to the standard error schema."""

    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = detail.get("code", "INTERNAL")
    message = detail.get("message_fa", "خطای ناشناخته رخ داد")
    correlation_id = get_correlation_id()
    payload = {
        "error": {
            "code": code,
            "message_fa": message,
            "correlation_id": correlation_id,
        }
    }
    details = detail.get("details") if isinstance(detail, dict) else None
    if details:
        payload["details"] = details
    if isinstance(detail, dict) and detail.get("hint"):
        payload["error"]["hint"] = detail["hint"]
    headers = dict(exc.headers or {})
    headers.setdefault("X-Correlation-ID", correlation_id)
    headers.setdefault("X-Error-Code", code)
    return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)



def _hash_body(body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(body)
    return digest.hexdigest()


def _sanitize_header_token(value: str) -> str:
    if not value:
        return ""
    return ZERO_WIDTH_RE.sub("", value.strip())


class JWTValidationError(Exception):
    """Raised when JWT validation fails."""


def _decode_jwt(token: str, *, secret: str, leeway: int) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTValidationError("invalid format")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise JWTValidationError("invalid payload") from exc
    if header.get("alg") != "HS256":
        raise JWTValidationError("unsupported alg")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature = _b64decode_bytes(signature_b64)
    if not hmac.compare_digest(expected_signature, signature):
        raise JWTValidationError("signature mismatch")
    now = time.time()
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and now > exp + leeway:
        raise JWTValidationError("expired")
    iat = payload.get("iat")
    if isinstance(iat, (int, float)) and iat - leeway > now:
        raise JWTValidationError("iat in future")
    return payload


def _b64decode(segment: str) -> str:
    return _b64decode_bytes(segment).decode("utf-8")


def _b64decode_bytes(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _hash_consumer_id(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8"))
    return digest.hexdigest()

