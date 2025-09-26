"""Hardened API middleware components."""
from __future__ import annotations

import base64
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
from starlette.types import ASGIApp

from .observability import (
    Observability,
    get_correlation_id,
    get_consumer_id,
    set_consumer_id,
    set_correlation_id,
    set_request_id,
)
from .patterns import ascii_token_pattern, zero_width_pattern
from .rate_limit_backends import RateLimitBackend, RateLimitDecision
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


class ContentTypeMismatchError(Exception):
    """Raised when the request content-type header is incorrect."""

    def __init__(self, detail: list[dict[str, object]]) -> None:
        super().__init__("content-type mismatch")
        self.detail = detail
        self.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        self.error_code = "VALIDATION_ERROR"


class BodyTooLargeError(Exception):
    """Raised when the incoming request body exceeds the configured limit."""

    def __init__(self, detail: list[dict[str, object]]) -> None:
        super().__init__("body too large")
        self.detail = detail
        self.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        self.error_code = "VALIDATION_ERROR"


class ContentTypeValidationMiddleware(BaseHTTPMiddleware):
    """Rejects requests that do not provide the required content-type."""

    def __init__(self, app: ASGIApp, *, methods: Iterable[str], paths: Iterable[str] | None = None) -> None:
        super().__init__(app)
        self._methods = {m.upper() for m in methods}
        self._paths = {path for path in (paths or ())}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method.upper() in self._methods:
            if self._paths and not any(
                request.url.path == path or request.url.path.startswith(f"{path}/")
                for path in self._paths
            ):
                return await call_next(request)
            content_type = (request.headers.get("content-type") or "").strip().lower()
            if content_type != "application/json; charset=utf-8":
                return build_error_response(
                    HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "VALIDATION_ERROR",
                            "message_fa": "درخواست نامعتبر است",
                            "details": [
                                {
                                    "loc": ["header", "Content-Type"],
                                    "msg": "نوع محتوا باید application/json; charset=utf-8 باشد",
                                    "type": "value_error.content_type",
                                }
                            ],
                        },
                    )
                )
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Prevents oversized payloads from reaching the router."""

    def __init__(self, app: ASGIApp, *, limit_bytes: int, methods: Iterable[str], paths: Iterable[str] | None = None) -> None:
        super().__init__(app)
        self._limit = limit_bytes
        self._methods = {m.upper() for m in methods}
        self._paths = {path for path in (paths or ())}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method.upper() in self._methods:
            if self._paths and not any(
                request.url.path == path or request.url.path.startswith(f"{path}/")
                for path in self._paths
            ):
                return await call_next(request)
            body = await request.body()
            if len(body) > self._limit:
                return build_error_response(
                    HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "VALIDATION_ERROR",
                            "message_fa": "درخواست نامعتبر است",
                            "details": [
                                {
                                    "loc": ["body"],
                                    "msg": "حجم بدنهٔ درخواست بیش از حد مجاز است",
                                    "type": "value_error.body_size",
                                    "ctx": {"limit": self._limit},
                                }
                            ],
                        },
                    )
                )
            request.state.raw_body = body
        return await call_next(request)


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


class RateLimiter:
    """Sliding window limiter delegating to a backend."""

    def __init__(self, *, backend: RateLimitBackend, capacity: int, refill_rate_per_sec: float) -> None:
        self._backend = backend
        self._capacity = capacity
        self._refill_rate = refill_rate_per_sec

    async def consume(self, key: str) -> RateLimitDecision:
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
        route = request.url.path
        decision = await self._limiter.consume(f"rl:{route}:{consumer_id}")
        if not decision.allowed:
            self._observability.increment_rate_limit(route)
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
        remaining = max(0, int(decision.remaining))
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
            return response
        except (ContentTypeMismatchError, BodyTooLargeError) as exc:
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            error_code = "VALIDATION_ERROR"
            outcome = "ERROR"
            http_exc = HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message_fa": "درخواست نامعتبر است",
                    "details": getattr(exc, "detail", []),
                },
            )
            return build_error_response(http_exc)
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
    if "details" in detail and detail["details"]:
        payload["error"]["details"] = detail["details"]
    if "hint" in detail and detail["hint"]:
        payload["error"]["hint"] = detail["hint"]
    headers = dict(exc.headers or {})
    headers.setdefault("X-Correlation-ID", correlation_id)
    return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)


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

