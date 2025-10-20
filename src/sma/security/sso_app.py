from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Awaitable, Callable, Mapping

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from auth.errors import AuthError
from auth.metrics import AuthMetrics
from auth.oidc_adapter import OIDCAdapter
from auth.saml_adapter import SAMLAdapter
from auth.session_store import SessionStore
from sma.config.env_schema import SSOConfig
from sma.app.context import reset_debug_context
from sma.debug.debug_context import DebugContext
from sma.reliability.clock import Clock

_HTTP_STATUS_TOO_MANY_REQUESTS = 429
_HTTP_STATUS_SERVICE_UNAVAILABLE = 503


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, limit: int, window_seconds: float, clock: Clock) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._state: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["RateLimit"]
        key = request.headers.get("X-RateLimit-Key") or request.client.host or "global"
        now = self._clock.now().timestamp()
        async with self._lock:
            count, reset_at = self._state.get(key, (0, now + self._window_seconds))
            if now >= reset_at:
                count = 0
                reset_at = now + self._window_seconds
            if count >= self._limit and request.method == "POST":
                raise HTTPException(status_code=_HTTP_STATUS_TOO_MANY_REQUESTS, detail="نرخ درخواست مجاز نیست.")
            self._state[key] = (count + 1, reset_at)
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, ttl_seconds: int, clock: Clock) -> None:
        super().__init__(app)
        self._ttl = ttl_seconds
        self._clock = clock
        self._responses: dict[str, tuple[bytes, float, dict[str, str]]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Idempotency"]
        if request.method != "POST":
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="کلید تکرار الزامی است.")
        now = self._clock.now().timestamp()
        async with self._lock:
            cached = self._responses.get(key)
            if cached and cached[1] + self._ttl > now:
                body, _, headers = cached
                response = JSONResponse(content=json.loads(body.decode("utf-8")))
                response.headers.update(headers)
                response.headers["X-Middleware-Order"] = ",".join(request.state.middleware_order)
                return response
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        headers = dict(response.headers)
        async with self._lock:
            self._responses[key] = (body, now, headers)
        replay = JSONResponse(content=json.loads(body.decode("utf-8")), status_code=response.status_code, headers=headers)
        replay.headers["X-Middleware-Order"] = ",".join(request.state.middleware_order)
        return replay


class CallbackAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config: SSOConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Auth"]
        if request.method == "POST" and not self._config.post_ready:
            response = JSONResponse(
                {"detail": "سامانه در حالت آماده‌سازی است."},
                status_code=_HTTP_STATUS_SERVICE_UNAVAILABLE,
            )
            order = getattr(request.state, "middleware_order", [])
            if order:
                response.headers["X-Middleware-Order"] = ",".join(order)
            return response
        return await call_next(request)


def _resolve_correlation_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    if header and header.strip():
        return header.strip()
    return uuid.uuid4().hex


def create_sso_app(
    *,
    config: SSOConfig,
    clock: Clock,
    session_store: SessionStore,
    metrics: AuthMetrics,
    audit_sink: Callable[[str, str, Mapping[str, Any]], Awaitable[None]],
    http_client: httpx.AsyncClient,
    ldap_mapper: Callable[[Mapping[str, Any]], Awaitable[tuple[str, str]]] | None,
    metrics_token: str,
    debug_context_factory: Callable[[Request], DebugContext] | None = None,
) -> FastAPI:
    app = FastAPI()

    # Register middlewares in reverse order to satisfy RateLimit -> Idempotency -> Auth execution
    app.add_middleware(CallbackAuthMiddleware, config=config)
    app.add_middleware(IdempotencyMiddleware, ttl_seconds=config.session_ttl_seconds, clock=clock)
    app.add_middleware(RateLimitMiddleware, limit=30, window_seconds=1.0, clock=clock)

    oidc_adapter = OIDCAdapter(
        settings=config.oidc,
        http_client=http_client,
        session_store=session_store,
        metrics=metrics,
        clock=clock,
        audit_sink=audit_sink,
        ldap_mapper=ldap_mapper,
    ) if config.oidc else None

    saml_adapter = SAMLAdapter(
        settings=config.saml,
        session_store=session_store,
        metrics=metrics,
        clock=clock,
        audit_sink=audit_sink,
        ldap_mapper=ldap_mapper,
    ) if config.saml else None

    @app.get("/auth/login")
    async def login(request: Request, provider: str | None = None) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request)
        chosen = provider or ("oidc" if oidc_adapter else "saml")
        if chosen == "oidc" and oidc_adapter:
            url = await oidc_adapter.authorization_url(state=correlation_id, nonce=uuid.uuid4().hex)
        elif chosen == "saml" and saml_adapter:
            url = f"{config.saml.idp_metadata_xml}#login"
        else:
            raise HTTPException(status_code=400, detail="ارائه‌دهنده نامعتبر است.")
        response = JSONResponse({"url": url, "provider": chosen})
        response.set_cookie(
            "sso_state",
            value=correlation_id,
            max_age=300,
            httponly=True,
            samesite="lax",
            secure=os.getenv("ENVIRONMENT") == "production",
        )
        return response

    @app.post("/auth/callback")
    async def callback(request: Request) -> JSONResponse:
        body = await request.json()
        provider = body.get("provider") or ("oidc" if "code" in body else "saml")
        correlation_id = _resolve_correlation_id(request)
        request_id = correlation_id
        debug_ctx = debug_context_factory(request) if debug_context_factory else None
        if debug_ctx:
            request.state.debug_ctx = debug_ctx
        token = getattr(getattr(request, "state", object()), "debug_ctx_token", None) if debug_ctx else None
        try:
            if provider == "oidc" and oidc_adapter:
                code = body.get("code")
                if not code:
                    raise HTTPException(status_code=400, detail="کد اعتبارسنجی الزامی است.")
                session = await oidc_adapter.authenticate(
                    code=code,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    debug=debug_ctx,
                )
            elif provider == "saml" and saml_adapter:
                assertion = body.get("assertion")
                if not assertion:
                    raise HTTPException(status_code=400, detail="پیام هویتی الزامی است.")
                session = await saml_adapter.authenticate(
                    assertion=assertion,
                    correlation_id=correlation_id,
                    request_id=request_id,
                )
            else:
                raise HTTPException(status_code=400, detail="ارائه‌دهنده نامعتبر است.")
        except AuthError as exc:
            status = 403 if exc.code == "AUTH_FORBIDDEN" else 502 if exc.code == "AUTH_IDP_ERROR" else 400
            raise HTTPException(status_code=status, detail=exc.message_fa) from exc
        finally:
            if token is not None:
                reset_debug_context(token)
                setattr(request.state, "debug_ctx_token", None)
        response = JSONResponse({"status": "ok", "role": session.role, "center_scope": session.center_scope})
        order = getattr(request.state, "middleware_order", [])
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        response.set_cookie(
            "bridge_session",
            value=session.sid,
            max_age=config.session_ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=os.getenv("ENVIRONMENT") == "production",
        )
        return response

    @app.post("/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        sid = request.cookies.get("bridge_session")
        if sid:
            await session_store.delete(sid)
        response = JSONResponse({"status": "ok"})
        order = getattr(request.state, "middleware_order", [])
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        response.delete_cookie("bridge_session")
        return response

    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        token = request.headers.get("Authorization")
        if token != f"Bearer {metrics_token}":
            raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        data = generate_latest(metrics.registry)
        return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    return app


__all__ = ["create_sso_app"]
