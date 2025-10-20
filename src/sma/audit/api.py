"""FastAPI router exposing audit governance endpoints and SSR views."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import generate_latest
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse

from .enums import AuditAction, AuditActorRole, AuditOutcome
from .exporter import AuditExporter
from .repository import AuditQuery
from .security import AuditSignedURLProvider, SignedURLVerifier
from .service import AuditService

_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


@dataclass(slots=True)
class Principal:
    role: AuditActorRole
    center_scope: str | None = None


class AuditListParams(BaseModel):
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")
    action: AuditAction | None = None
    role: AuditActorRole | None = Field(default=None, alias="actor")
    center: str | None = None
    outcome: AuditOutcome | None = None
    page: int = Field(default=1, ge=1, le=200)
    page_size: int = Field(default=50, ge=1, le=500)

    @field_validator("center")
    @classmethod
    def _sanitize_center(cls, value: str | None):
        if value in (None, "", "0", "\u200c", "\u200f"):
            return None
        cleaned = value.translate(_FA_TO_EN).replace("\u200c", "").replace("\u200f", "").strip()
        if not cleaned:
            return None
        if len(cleaned) > 64:
            raise ValueError("شناسه مرکز بیش از حد طولانی است")
        return cleaned

    @model_validator(mode="after")
    def _validate_dates(self):  # type: ignore[override]
        if self.to_date is not None and self.from_date is not None and self.to_date < self.from_date:
            raise ValueError("بازه تاریخ نامعتبر است")
        return self


class ExportParams(BaseModel):
    format: str = Field(alias="format")
    bom: bool = Field(default=False)
    token: str | None = Field(default=None, alias="token")
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str):
        lowered = value.lower()
        if lowered not in {"csv", "json"}:
            raise ValueError("فرمت نامعتبر است")
        return lowered

    @model_validator(mode="after")
    def _validate_range(self):  # type: ignore[override]
        if self.to_date is not None and self.from_date is not None and self.to_date < self.from_date:
            raise ValueError("بازه تاریخ نامعتبر است")
        return self


def get_principal(request: Request) -> Principal:
    stored = getattr(request.state, "audit_principal", None)
    if stored is not None:
        return stored
    return Principal(role=AuditActorRole.ADMIN, center_scope=None)


class _AuditRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int, window_seconds: int, clock: Callable[[], datetime]) -> None:
        super().__init__(app)
        self._limit = max(1, limit)
        self._window_seconds = max(1, window_seconds)
        self._clock = clock
        self._state: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        chain = getattr(request.state, "middleware_order", [])
        chain.append("RateLimit")
        request.state.middleware_order = chain
        rid = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or uuid4().hex
        request.state.correlation_id = rid
        rate_key = request.headers.get("X-RateLimit-Key") or request.headers.get("X-Role") or "global"
        if not await self._allow(rate_key):
            return _json_error("AUDIT_RATE_LIMIT", "درخواست‌های بیش از حد.", status_code=429)
        return await call_next(request)

    async def _allow(self, key: str) -> bool:
        now = int(self._clock().timestamp())
        current_window = now // self._window_seconds
        scoped_key = f"{key}:{current_window}"
        async with self._lock:
            count, window = self._state.get(scoped_key, (0, current_window))
            count += 1
            self._state[scoped_key] = (count, window)
            # cleanup expired windows lazily
            stale = [k for k, (_, win) in self._state.items() if win < current_window]
            for item in stale:
                self._state.pop(item, None)
            return count <= self._limit


class _AuditIdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, ttl_seconds: int, clock: Callable[[], datetime]) -> None:
        super().__init__(app)
        self._ttl = max(1, ttl_seconds)
        self._clock = clock
        self._store: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        chain = getattr(request.state, "middleware_order", [])
        chain.append("Idempotency")
        request.state.middleware_order = chain
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            return _json_error("AUDIT_VALIDATION_ERROR", "کلید عدم تکرار الزامی است.", status_code=400)
        now = int(self._clock().timestamp())
        async with self._lock:
            await self._purge(now)
            expires = now + self._ttl
            existing = self._store.get(key)
            if existing and existing > now:
                return _json_error("AUDIT_DUPLICATE_REQUEST", "درخواست تکراری است.", status_code=409)
            self._store[key] = expires
        return await call_next(request)

    async def _purge(self, now: int) -> None:
        expired = [k for k, expiry in self._store.items() if expiry <= now]
        for key in expired:
            self._store.pop(key, None)


class _AuditAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, service: AuditService | None) -> None:
        super().__init__(app)
        self._service = service

    async def dispatch(self, request: Request, call_next):
        chain = getattr(request.state, "middleware_order", [])
        chain.append("Auth")
        request.state.middleware_order = chain
        rid = getattr(request.state, "correlation_id", None) or request.headers.get("X-Correlation-ID") or uuid4().hex
        role_header = request.headers.get("X-Role")
        center_header = request.headers.get("X-Center")
        try:
            principal = _resolve_principal(role_header, center_header)
        except HTTPException as exc:
            await self._record_auth_event(
                rid=rid,
                outcome=AuditOutcome.ERROR,
                path=request.url.path,
                error_code="AUTH_INVALID",
                center=_normalize_center(center_header),
                role=None,
            )
            return _json_response(exc)
        request.state.audit_principal = principal
        await self._record_auth_event(
            rid=rid,
            outcome=AuditOutcome.OK,
            path=request.url.path,
            error_code=None,
            center=principal.center_scope,
            role=principal.role,
        )
        response = await call_next(request)
        order = getattr(request.state, "middleware_order", [])
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        return response

    async def _record_auth_event(
        self,
        *,
        rid: str,
        outcome: AuditOutcome,
        path: str,
        error_code: str | None,
        center: str | None,
        role: AuditActorRole | None,
    ) -> None:
        if self._service is None:
            return
        actor_role = role or AuditActorRole.ADMIN
        await self._service.record_event(
            actor_role=actor_role,
            center_scope=center,
            action=AuditAction.AUTHN_OK if outcome is AuditOutcome.OK else AuditAction.AUTHN_FAIL,
            resource_type="auth",
            resource_id=path,
            request_id=rid,
            outcome=outcome,
            error_code=error_code,
        )


def create_audit_api(
    *,
    service: AuditService,
    exporter: AuditExporter,
    secret_key: str | None = "audit-secret",
    signer: SignedURLVerifier | None = None,
    metrics_token: str | None = None,
    rate_limit_per_minute: int = 120,
    rate_limit_window_seconds: int = 60,
    idempotency_ttl_seconds: int = 86_400,
) -> FastAPI:
    signer = signer or AuditSignedURLProvider(secret_key or "audit-secret", clock=service.now)
    router = APIRouter()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @router.get("/audit/export")
    async def export_audit(
        params: ExportParams = Depends(),
        principal: Principal = Depends(get_principal),
        request_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    ) -> StreamingResponse:
        rid = request_id or uuid4().hex
        resource_key = _resource_key(principal)
        if not params.token or not signer.verify(resource_key, params.token, now=service.now()):
            raise HTTPException(
                status_code=403,
                detail={"error_code": "AUDIT_SIGNED_URL_REQUIRED", "message": "لینک دانلود امضاشده معتبر نیست."},
            )
        query = _build_query(
            service,
            AuditListParams(
                from_date=params.from_date,
                to_date=params.to_date,
                action=None,
                role=principal.role,
                center=principal.center_scope,
                outcome=None,
                page=1,
                page_size=500,
            ),
            principal,
        )
        result = await exporter.export(
            fmt=params.format,
            query=query,
            bom=params.bom,
            rid=rid,
            actor_role=principal.role,
            center_scope=principal.center_scope,
        )
        await service.record_event(
            actor_role=principal.role,
            center_scope=principal.center_scope,
            action=AuditAction.EXPORT_DOWNLOADED,
            resource_type="audit",
            resource_id=result.path.name,
            request_id=rid,
            outcome=AuditOutcome.OK,
            artifact_sha256=result.sha256,
        )
        media_type = "text/csv" if params.format == "csv" else "application/json"
        filename = result.path.name

        async def iterator():
            loop = asyncio.get_event_loop()
            with result.path.open("rb") as handle:
                while True:
                    chunk = await loop.run_in_executor(None, handle.read, 8192)
                    if not chunk:
                        break
                    yield chunk

        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        return StreamingResponse(iterator(), media_type=media_type, headers=headers)

    @router.get("/audit", response_class=JSONResponse)
    async def list_audit(
        params: AuditListParams = Depends(),
        principal: Principal = Depends(get_principal),
        request_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    ) -> JSONResponse:
        rid = request_id or uuid4().hex
        query = _build_query(service, params, principal)
        events = await service.list_events(query)
        payload = {
            "rid": rid,
            "items": [
                {
                    "id": event.id,
                    "ts": event.ts.isoformat(),
                    "actor_role": event.actor_role.value,
                    "center_scope": event.center_scope,
                    "action": event.action.value,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "request_id": event.request_id,
                    "outcome": event.outcome.value,
                    "artifact_sha256": event.artifact_sha256,
                }
                for event in events
            ],
            "count": len(events),
        }
        return JSONResponse(payload)

    @router.get("/audit/{event_id}")
    async def get_event(event_id: int) -> JSONResponse:
        event = await service.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="رویداد یافت نشد")
        payload = {
            "id": event.id,
            "ts": event.ts.isoformat(),
            "actor_role": event.actor_role.value,
            "center_scope": event.center_scope,
            "action": event.action.value,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "request_id": event.request_id,
            "outcome": event.outcome.value,
            "error_code": event.error_code,
            "artifact_sha256": event.artifact_sha256,
        }
        return JSONResponse(payload)

    @router.get("/ui/audit", response_class=HTMLResponse)
    async def audit_ui(
        request: Request,
        params: AuditListParams = Depends(),
        principal: Principal = Depends(get_principal),
    ) -> HTMLResponse:
        query = _build_query(service, params, principal)
        events = await service.list_events(query)
        token = signer.sign(_resource_key(principal))
        context = {
            "request": request,
            "events": events,
            "filters": params,
            "principal": principal,
            "signed_url": f"/audit/export?format=csv&token={token}",
        }
        return templates.TemplateResponse(request, "audit/index.html", context)

    @router.get("/ui/audit/exports", response_class=HTMLResponse)
    async def audit_exports_ui(request: Request, principal: Principal = Depends(get_principal)) -> HTMLResponse:
        token = signer.sign(_resource_key(principal))
        context = {
            "request": request,
            "rtl": True,
            "signed_url": f"/audit/export?format=csv&token={token}",
        }
        return templates.TemplateResponse(request, "audit/exports.html", context)

    @router.get("/metrics")
    async def metrics_endpoint(authorization: str = Header(default="")) -> PlainTextResponse:
        if metrics_token is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "AUDIT_METRICS_DISABLED", "message": "متریک در این سرویس فعال نیست."},
            )
        if authorization != f"Bearer {metrics_token}":
            raise HTTPException(
                status_code=401,
                detail={"error_code": "AUDIT_METRICS_FORBIDDEN", "message": "توکن دسترسی نامعتبر است."},
            )
        data = generate_latest(service.metrics_registry).decode("utf-8")
        return PlainTextResponse(data, media_type="text/plain; version=0.0.4")

    app = FastAPI()
    app.state.audit_service = service
    app.state.audit_signer = signer
    app.include_router(router)

    app.add_middleware(_AuditAuthMiddleware, service=service)
    app.add_middleware(_AuditIdempotencyMiddleware, ttl_seconds=idempotency_ttl_seconds, clock=service.now)
    app.add_middleware(
        _AuditRateLimitMiddleware,
        limit=max(1, rate_limit_per_minute),
        window_seconds=max(1, rate_limit_window_seconds),
        clock=service.now,
    )

    return app


def _resource_key(principal: Principal) -> str:
    scope = principal.center_scope or "*"
    return f"/audit/export:{principal.role.value}:{scope}"


def _build_query(service: AuditService, params: AuditListParams, principal: Principal) -> AuditQuery:
    from_ts = _combine(service, params.from_date, time.min)
    to_ts = _combine(service, params.to_date, time.max)
    role = params.role or principal.role
    center = params.center or principal.center_scope
    return AuditQuery(
        from_ts=from_ts,
        to_ts=to_ts,
        actor_role=role,
        action=params.action,
        center_scope=center,
        outcome=params.outcome,
        limit=params.page_size,
        offset=(params.page - 1) * params.page_size,
    )


def _combine(service: AuditService, day: date | None, default_time: time) -> datetime | None:
    if day is None:
        return None
    dt = datetime.combine(day, default_time)
    return dt.replace(tzinfo=service.timezone)


def _resolve_principal(role_header: str | None, center_header: str | None) -> Principal:
    role_value = (role_header or "ADMIN").strip().upper()
    try:
        role = AuditActorRole(role_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AUDIT_VALIDATION_ERROR", "message": "نقش کاربر نامعتبر است."},
        ) from exc
    return Principal(role=role, center_scope=_normalize_center(center_header))


def _normalize_center(center: str | None) -> str | None:
    if center in (None, "", "0", "۰۰", "\u200c", "\u200f"):
        return None
    cleaned = center.translate(_FA_TO_EN).replace("\u200c", "").replace("\u200f", "").strip()
    if not cleaned or cleaned == "0":
        return None
    return cleaned[:64]


def _json_error(code: str, message: str, *, status_code: int) -> StarletteJSONResponse:
    return StarletteJSONResponse({"error_code": code, "message": message}, status_code=status_code)


def _json_response(exc: HTTPException) -> StarletteJSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    detail.setdefault("error_code", "AUDIT_VALIDATION_ERROR")
    return StarletteJSONResponse(detail, status_code=exc.status_code)


__all__ = ["create_audit_api", "Principal"]
