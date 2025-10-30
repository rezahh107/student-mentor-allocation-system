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

# from auth.errors import AuthError # حذف شد یا تغییر کرد
# from auth.metrics import AuthMetrics
# from auth.oidc_adapter import OIDCAdapter
# from auth.saml_adapter import SAMLAdapter
# from auth.session_store import SessionStore
# from sma.config.env_schema import SSOConfig
# from sma.app.context import reset_debug_context
# from sma.debug.debug_context import DebugContext
# from sma.reliability.clock import Clock
# این ماژول‌ها ممکن است همچنان مورد نیاز باشند، اما کلاس‌ها/توابعی که مربوط به امنیت هستند باید تغییر کنند

# تغییر مقادیر کد وضعیت امنیتی (اختیاری، اگر دیگر مورد استفاده نباشند)
# _HTTP_STATUS_TOO_MANY_REQUESTS = 429 # حذف شد یا تغییر کرد
# _HTTP_STATUS_SERVICE_UNAVAILABLE = 503 # حذف شد یا تغییر کرد
_HTTP_STATUS_OK = 200


# --- تغییر میدلویر RateLimit ---
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, limit: int, window_seconds: float, clock) -> None: # Clock را تغییر دهیم
        super().__init__(app)
        # self._limit = limit # حذف شد یا تغییر کرد
        # self._window_seconds = window_seconds # حذف شد یا تغییر کرد
        # self._clock = clock # حذف شد یا تغییر کرد
        # self._state: dict[str, tuple[int, float]] = {} # حذف شد یا تغییر کرد
        # self._lock = asyncio.Lock() # حذف شد یا تغییر کرد

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # افزودن به زنجیره میدلویر (می‌توان حذف کرد)
        # request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["RateLimit"]
        # تمام منطق امنیتی حذف شد
        # key = request.headers.get("X-RateLimit-Key") or request.client.host or "global"
        # now = self._clock.now().timestamp()
        # async with self._lock: ...
        # if count >= self._limit and request.method == "POST": ...
        # self._state[key] = (count + 1, reset_at)
        return await call_next(request) # تغییر داده شد


# --- تغییر میدلویر Idempotency ---
class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, ttl_seconds: int, clock) -> None: # Clock را تغییر دهیم
        super().__init__(app)
        # self._ttl = ttl_seconds # حذف شد یا تغییر کرد
        # self._clock = clock # حذف شد یا تغییر کرد
        # self._responses: dict[str, tuple[bytes, float, dict[str, str]]] = {} # حذف شد یا تغییر کرد
        # self._lock = asyncio.Lock() # حذف شد یا تغییر کرد

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # افزودن به زنجیره میدلویر (می‌توان حذف کرد)
        # request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Idempotency"]
        # تمام منطق امنیتی/ایدمپوتنسی حذف شد
        # if request.method != "POST": ...
        # key = request.headers.get("Idempotency-Key")
        # if not key: ...
        # now = self._clock.now().timestamp()
        # async with self._lock: ...
        # cached = self._responses.get(key) ...
        # response = JSONResponse(...) ...
        # async for chunk in response.body_iterator: ...
        # async with self._lock: ...
        # replay = JSONResponse(...) ...
        return await call_next(request) # تغییر داده شد


# --- تغییر میدلویر CallbackAuth (که بیشتر یک چک وضعیت است، اما در مسیر امنیتی قرار دارد) ---
class CallbackAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config) -> None: # SSOConfig را تغییر دهیم
        super().__init__(app)
        # self._config = config # حذف شد یا تغییر کرد

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # افزودن به زنجیره میدلویر (می‌توان حذف کرد)
        # request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Auth"]
        # تمام منطق امنیتی/چک وضعیت حذف شد
        # if request.method == "POST" and not self._config.post_ready: ...
        return await call_next(request) # تغییر داده شد


def _resolve_correlation_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    if header and header.strip():
        return header.strip()
    return uuid.uuid4().hex


def create_sso_app(
    *,
    config, # SSOConfig, # تغییر داده شد
    clock, # Clock, # تغییر داده شد
    session_store, # SessionStore, # تغییر داده شد
    metrics, # AuthMetrics, # تغییر داده شد
    audit_sink: Callable[[str, str, Mapping[str, Any]], Awaitable[None]],
    http_client: httpx.AsyncClient,
    ldap_mapper: Callable[[Mapping[str, Any]], Awaitable[tuple[str, str]]] | None,
    # metrics_token: str, # حذف شد یا تغییر کرد
    debug_context_factory: Callable[[Request], DebugContext] | None = None, # DebugContext را تغییر دهیم
) -> FastAPI:
    app = FastAPI()

    # افزودن میدلویرهای امنیتی حذف شد
    # Register middlewares in reverse order to satisfy RateLimit -> Idempotency -> Auth execution
    # app.add_middleware(CallbackAuthMiddleware, config=config) # حذف شد
    # app.add_middleware(IdempotencyMiddleware, ttl_seconds=config.session_ttl_seconds, clock=clock) # حذف شد
    # app.add_middleware(RateLimitMiddleware, limit=30, window_seconds=1.0, clock=clock) # حذف شد
    # اگر میدلویرهای غیرامنیتی وجود داشتند، اینجا اضافه می‌شدند

    # ساخت اداپتورها (OIDC, SAML) - اگرچه در محیط توسعه بدون امنیت، ممکن است این اداپتورها نیز تغییر کنند یا غیرفعال شوند
    # برای سادگی، فرض می‌کنیم آن‌ها همچنان ساخته می‌شوند، اما عملکرد امنیتی ندارند
    # این بستگی به پیاده‌سازی داخلی OIDCAdapter و SAMLAdapter دارد که در فایل‌های دیگری قرار دارند
    # برای این فایل، ما فقط اضافه شدن میدلویرها را متوقف می‌کنیم
    # oidc_adapter = OIDCAdapter(...) # اگر لازم باشد، در فایل مربوطه تغییر می‌کند
    # saml_adapter = SAMLAdapter(...) # اگر لازم باشد، در فایل مربوطه تغییر می‌کند
    # در اینجا، فقط فرض می‌کنیم متغیرهایی که در توابع زیر ممکن است مورد استفاده قرار گیرند، تعریف شده‌اند
    # یا اینکه توابع زیر نیز طوری تغییر کنند که از این اداپتورها استفاده نکنند
    # برای اینجا، این اداپتورها را نادیده می‌گیریم یا None فرض می‌کنیم
    oidc_adapter = None # تغییر داده شد
    saml_adapter = None # تغییر داده شد

    @app.get("/auth/login")
    async def login(request: Request, provider: str | None = None) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request)
        # chosen = provider or ("oidc" if oidc_adapter else "saml") # تغییر داده شد
        chosen = provider or "oidc" # تغییر داده شد
        # if chosen == "oidc" and oidc_adapter: ...
        # elif chosen == "saml" and saml_adapter: ...
        # else: ...
        # برای توسعه، ممکن است فقط یک URL ساختگی یا پیامی بازگردانده شود
        # اما برای حفظ ساختار، فقط یک استثنا موقت ایجاد می‌کنیم یا یک پاسخ ساده
        # یا فرض کنیم oidc_adapter و saml_adapter طوری تغییر کرده‌اند که کار کنند
        # برای اینجا، فرض می‌کنیم این بخش‌ها در فایل‌های مربوطه تغییر کرده‌اند
        # و این تابع همچنان کار می‌کند، اما ممکن است بدون احراز هویت واقعی باشد
        # برای سادگی، فقط یک پیام برمی‌گردانیم
        return JSONResponse({"detail": "Login endpoint disabled in dev mode.", "provider": chosen}) # تغییر داده شد
        # یا ادامه منطق قبلی با فرض وجود اداپتورهای تغییر یافته
        # url = await oidc_adapter.authorization_url(...) # فقط اگر oidc_adapter تغییر کرده باشد
        # response = JSONResponse({"url": url, "provider": chosen})
        # response.set_cookie(...) # فقط اگر لازم باشد
        # return response

    @app.post("/auth/callback")
    async def callback(request: Request) -> JSONResponse:
        # body = await request.json()
        # provider = body.get("provider") ...
        # correlation_id = _resolve_correlation_id(request)
        # request_id = correlation_id
        # debug_ctx = debug_context_factory(request) if debug_context_factory else None
        # if debug_ctx: ...
        # token = ... # از debug_ctx
        # try: ...
        #     if provider == "oidc" and oidc_adapter: ...
        #     elif provider == "saml" and saml_adapter: ...
        #     else: ...
        # except AuthError as exc: ...
        # finally: ...
        #     if token is not None: ...
        # response = JSONResponse({"status": "ok", "role": session.role, "center_scope": session.center_scope})
        # order = getattr(request.state, "middleware_order", [])
        # if order: ...
        # response.set_cookie(...) # فقط اگر لازم باشد
        # return response
        # برای توسعه، ممکن است فقط یک پاسخ موقتی یا یک سشن ساختگی بازگردانده شود
        return JSONResponse({"status": "dev_callback_ok", "role": "ADMIN", "center_scope": None}) # تغییر داده شد

    @app.post("/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        # sid = request.cookies.get("bridge_session")
        # if sid: ...
        #     await session_store.delete(sid) # فقط اگر session_store تغییر کرده باشد
        # response = JSONResponse({"status": "ok"})
        # order = getattr(request.state, "middleware_order", [])
        # if order: ...
        # response.delete_cookie("bridge_session")
        # return response
        # برای توسعه، فقط یک پاسخ موقتی
        return JSONResponse({"status": "dev_logout_ok"}) # تغییر داده شد

    # تغییر endpoint /metrics
    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        # چک توکن حذف شد
        # token = request.headers.get("Authorization")
        # if token != f"Bearer {metrics_token}":
        #     raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        # فرض بر این است که 'metrics' شیء ثبت‌شده‌ای است که متریک‌ها را دارد
        # اگرچه در این فایل وارد نشده، اما ممکن است از طریق پارامتر 'metrics' به تابع داده شده باشد
        # اما چون این پارامتر را در مسیر تابع نمی‌بینیم، فرض می‌کنیم قبلاً در حوزه دید است
        # اگر 'metrics' فقط شامل متریک‌های امنیتی بود، ممکن است دیگر معنایی نداشته باشد
        # اما اگر متریک‌های سیستمی/غیرامنیتی هم داشت، ممکن است همچنان مفید باشد
        # برای اینجا، ما فقط از شیء 'metrics' که به تابع داده شده استفاده می‌کنیم
        data = generate_latest(metrics.registry) # فرض بر این است که registry وجود دارد
        return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    return app


__all__ = ["create_sso_app"]
