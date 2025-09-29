from __future__ import annotations

"""FastAPI router providing SSR ops dashboards in Persian."""

import uuid
from collections.abc import Callable
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import OpsSettings, get_settings
from .replica_adapter import ReplicaTimeoutError
from .service import OpsContext, OpsService

TEMPLATE_ENV = Environment(
    loader=FileSystemLoader("src/web/templates"),
    autoescape=select_autoescape(["html"]),
    enable_async=True,
)


ALLOWED_ROLES = {"ADMIN", "MANAGER"}


def _correlation_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    if header:
        return header
    return str(uuid.uuid4())


def _validate_role(role: str) -> str:
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="نقش نامعتبر است")
    return role


def _validate_center(center: Optional[str]) -> Optional[str]:
    if center in (None, "", "0", "\u200c", "\u200f"):
        return None
    if not isinstance(center, str):
        return None
    digits = center.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    if digits == "0":
        return None
    if digits and digits.isdigit() and 1 <= len(digits) <= 6 and digits[0] != "0":
        return digits
    raise HTTPException(status_code=400, detail="شناسهٔ مرکز نامعتبر است")


def build_ops_router(
    service_factory: Callable[[OpsSettings], OpsService],
    *,
    settings: OpsSettings | None = None,
) -> APIRouter:
    settings = settings or get_settings()
    router = APIRouter(prefix="/ui/ops")

    async def _render(template_name: str, **context: Any) -> Response:
        template = TEMPLATE_ENV.get_template(template_name)
        defaults = {
            "title": "پایش عملیات",
            "heading": context.pop("heading", "پایش عملیات"),
            "badge": context.pop("badge", "بدون شناسهٔ شخصی"),
        }
        html = await template.render_async(**defaults, **context)
        return HTMLResponse(html)

    def _ctx(request: Request, role: str, center: Optional[str]) -> OpsContext:
        corr = _correlation_id(request)
        validated_center = _validate_center(center)
        validated_role = _validate_role(role)
        return OpsContext(role=validated_role, center_scope=validated_center, correlation_id=corr)

    @router.get("/home", response_class=HTMLResponse)
    async def home(request: Request, role: str = "ADMIN", center: Optional[str] = None) -> Response:
        ctx = _ctx(request, role, center)
        return await _render(
            "ops_home.html",
            heading="داشبورد عملیات",
            badge=f"نقش: {ctx.role}",
            context=ctx,
            settings=settings,
        )

    @router.get("/exports", response_class=HTMLResponse)
    async def exports(
        request: Request,
        role: str = "ADMIN",
        center: Optional[str] = None,
        service: OpsService = Depends(lambda: service_factory(settings)),
    ) -> Response:
        ctx = _ctx(request, role, center)
        try:
            payload = await service.load_exports(ctx)
        except ReplicaTimeoutError:
            payload = {"error": "عدم دسترسی به پایگاه گزارش‌گیری"}
        except Exception:
            payload = {"error": "بازیابی داده‌های برون‌سپاری با خطا مواجه شد"}
        return await _render(
            "ops_exports.html",
            payload=payload,
            ctx=ctx,
            heading="گزارش برون‌سپاری",
            badge=f"مرکز: {ctx.center_scope or 'همه'}",
        )

    @router.get("/uploads", response_class=HTMLResponse)
    async def uploads(
        request: Request,
        role: str = "ADMIN",
        center: Optional[str] = None,
        service: OpsService = Depends(lambda: service_factory(settings)),
    ) -> Response:
        ctx = _ctx(request, role, center)
        try:
            payload = await service.load_uploads(ctx)
        except ReplicaTimeoutError:
            payload = {"error": "عدم دسترسی به پایگاه گزارش‌گیری"}
        except Exception:
            payload = {"error": "بازیابی داده‌های بارگذاری با خطا مواجه شد"}
        return await _render(
            "ops_uploads.html",
            payload=payload,
            ctx=ctx,
            heading="وضعیت بارگذاری",
            badge=f"مرکز: {ctx.center_scope or 'همه'}",
        )

    @router.get("/slo", response_class=HTMLResponse)
    async def slo(request: Request) -> Response:
        ctx = _ctx(request, "ADMIN", None)
        return await _render(
            "ops_slo.html",
            ctx=ctx,
            thresholds=settings.slo_thresholds,
            heading="پایش SLO",
            badge="نقش: ADMIN",
        )

    return router


__all__ = ["build_ops_router"]
