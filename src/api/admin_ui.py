"""Lightweight operator dashboard served under ``/admin``."""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from textwrap import dedent
from typing import Callable, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.observability import Observability, get_correlation_id
from src.api.patterns import ascii_token_pattern
from src.api.security_hardening import constant_time_compare
from src.infrastructure.persistence.models import APIKeyModel


@dataclass(slots=True)
class AdminConfig:
    """Configuration for the admin surface."""

    admin_token: str


def build_admin_router(
    *,
    config: AdminConfig,
    session_factory: Callable[[], Session],
    observability: Observability,
    metrics_endpoint: str = "/metrics",
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    token_pattern = ascii_token_pattern(512)

    def _require_token(request: Request) -> None:
        header = request.headers.get("X-Admin-Token", "").strip()
        if not header or not token_pattern.fullmatch(header):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_REQUIRED", "message_fa": "توکن مدیریت نامعتبر است"},
            )
        if not constant_time_compare(header, config.admin_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_REQUIRED", "message_fa": "توکن مدیریت نامعتبر است"},
            )
        request.state.operator_id = _hash_operator(header)

    def _serialize(record: APIKeyModel) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "key_prefix": record.key_prefix,
            "is_active": record.is_active,
            "scopes": sorted({scope for scope in (record.scopes or "").split(",") if scope}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
            "disabled_at": record.disabled_at.isoformat() if getattr(record, "disabled_at", None) else None,
            "rotation_hint": record.rotation_hint,
        }

    def _response(payload: Mapping[str, object]) -> JSONResponse:
        enriched = dict(payload)
        enriched.setdefault("correlation_id", get_correlation_id())
        return JSONResponse(enriched)

    @router.get("", response_class=HTMLResponse)
    async def dashboard(request: Request, token: None = Depends(_require_token)) -> Response:  # type: ignore[assignment]
        nonce = secrets.token_urlsafe(16)
        template = dedent(
            """
            <!doctype html>
            <html lang="fa" dir="rtl">
            <head>
                <meta charset="utf-8" />
                <title>داشبورد مدیریت</title>
                <style nonce="__NONCE__">
                    body { font-family: sans-serif; margin: 2rem; direction: rtl; background:#fafafa; color:#222; }
                    h1, h2 { font-weight: 600; }
                    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
                    th, td { border: 1px solid #d0d0d0; padding: 0.5rem 0.75rem; text-align: right; }
                    th { background: #f0f0f0; }
                    button { padding: 0.6rem 1rem; margin: 0.25rem; border-radius: 0.5rem; border: 1px solid #444; background: white; cursor: pointer; }
                    button:focus { outline: 3px solid #1a73e8; outline-offset: 2px; }
                    .layout { display: grid; gap: 1.5rem; }
                    .panel { background: white; border-radius: 1rem; padding: 1.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
                    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); border: 0; }
                    .metrics-grid { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
                    .metric-card { border: 1px solid #ddd; border-radius: 0.75rem; padding: 1rem; background: #fff; }
                    .metric-card strong { font-size: 1.25rem; display: block; margin-bottom: 0.25rem; }
                </style>
            </head>
            <body>
                <a class="sr-only" href="#keys-table">پرش به فهرست کلیدها</a>
                <h1>داشبورد مدیریت</h1>
                <div id="status" aria-live="polite" class="panel"></div>
                <div class="layout">
                    <section class="panel" aria-labelledby="keys-title">
                        <h2 id="keys-title">کلیدهای API</h2>
                        <div class="actions" role="group" aria-label="عملیات کلید">
                            <button id="refresh-keys" type="button">بارگذاری مجدد</button>
                        </div>
                        <table id="keys-table" tabindex="0" aria-describedby="keys-title"></table>
                    </section>
                    <section class="panel" aria-labelledby="diagnostics-title">
                        <h2 id="diagnostics-title">نمای سلامت و محدودیت‌ها</h2>
                        <div class="metrics-grid" id="metrics-cards"></div>
                        <button id="refresh-diagnostics" type="button">به‌روزرسانی گزارش</button>
                    </section>
                    <section class="panel" aria-labelledby="raw-metrics-title">
                        <h2 id="raw-metrics-title">متریک‌های Prometheus</h2>
                        <pre id="metrics" tabindex="0" style="background:#f5f5f5; padding:1rem; max-height:320px; overflow:auto"></pre>
                        <button id="refresh-metrics" type="button">به‌روزرسانی متریک</button>
                    </section>
                </div>
                <script nonce="__NONCE__">
                    const TOKEN = '__TOKEN__';
                    const METRICS_URL = '__METRICS__';

                    async function loadKeys() {
                        const res = await fetch('./api-keys', {headers: {'X-Admin-Token': TOKEN}});
                        const table = document.getElementById('keys-table');
                        if (!res.ok) { table.innerHTML = '<tbody><tr><td>خطا در دریافت کلیدها</td></tr></tbody>'; return; }
                        const data = await res.json();
                        const rows = data.keys.map((k) => `
                            <tr>
                                <td>${k.name ?? '—'}</td>
                                <td>${k.key_prefix}</td>
                                <td>${k.is_active ? 'فعال' : 'غیرفعال'}</td>
                                <td>${k.scopes.join('، ') || '—'}</td>
                                <td>${k.last_used_at ?? '—'}</td>
                            </tr>`).join('');
                        table.innerHTML = `<thead><tr><th>نام</th><th>پیشوند</th><th>وضعیت</th><th>دامنه‌ها</th><th>آخرین استفاده</th></tr></thead><tbody>${rows}</tbody>`;
                        announce(data.message_fa);
                    }

                    async function loadDiagnostics() {
                        const res = await fetch('./diagnostics', {headers: {'X-Admin-Token': TOKEN}});
                        const cards = document.getElementById('metrics-cards');
                        if (!res.ok) { cards.innerHTML = '<div>خطا در دریافت گزارش سلامت</div>'; return; }
                        const data = await res.json();
                        const items = [];
                        for (const [route, value] of Object.entries(data.rate_limits)) {
                            items.push(`<div class="metric-card" role="group" aria-label="سهمیه مسیر ${route}"><strong>${value}</strong><span>ردشده برای ${route}</span></div>`);
                        }
                        for (const [state, value] of Object.entries(data.idempotency)) {
                            items.push(`<div class="metric-card" role="group" aria-label="وضعیت ایدمپوتنسی ${state}"><strong>${value}</strong><span>ایدیمپوتنسی ${state}</span></div>`);
                        }
                        items.push(`<div class="metric-card"><strong>${data.uptime_seconds}s</strong><span>زمان فعالیت سامانه</span></div>`);
                        cards.innerHTML = items.join('');
                        document.getElementById('status').textContent = `شناسه همبستگی: ${data.correlation_id}`;
                    }

                    async function loadMetrics() {
                        const res = await fetch(METRICS_URL, {headers: {'Authorization': 'Bearer ' + TOKEN}});
                        if (res.ok) {
                            document.getElementById('metrics').textContent = await res.text();
                        }
                    }

                    function announce(message) {
                        const status = document.getElementById('status');
                        status.textContent = message + ' — ' + new Date().toLocaleTimeString('fa-IR');
                    }

                    document.getElementById('refresh-keys').addEventListener('click', loadKeys);
                    document.getElementById('refresh-diagnostics').addEventListener('click', loadDiagnostics);
                    document.getElementById('refresh-metrics').addEventListener('click', loadMetrics);
                    loadKeys();
                    loadDiagnostics();
                    loadMetrics();
                </script>
            </body>
            </html>
            """
        )
        html = template.replace("__NONCE__", nonce).replace("__TOKEN__", config.admin_token).replace("__METRICS__", metrics_endpoint)
        headers = {
            "Content-Security-Policy": f"default-src 'self'; style-src 'self' 'nonce-{nonce}'; script-src 'self' 'nonce-{nonce}'",
        }
        return HTMLResponse(content=html, headers=headers)

    @router.get("/api-keys")
    async def list_keys(_: Request, token: None = Depends(_require_token)) -> JSONResponse:  # type: ignore[assignment]
        with session_factory() as session:
            records = session.execute(select(APIKeyModel).order_by(APIKeyModel.created_at.desc())).scalars().all()
        data = {"keys": [_serialize(record) for record in records], "message_fa": "فهرست کلیدها"}
        return _response(data)

    @router.post("/api-keys")
    async def create_key(request: Request, token: None = Depends(_require_token)) -> JSONResponse:  # type: ignore[assignment]
        body = await request.json()
        name = str(body.get("name") or "کلید جدید")
        scopes = sorted({str(scope) for scope in body.get("scopes", []) if scope})
        value = secrets.token_urlsafe(40)
        now = datetime.now(timezone.utc)
        salt = secrets.token_hex(16)
        prefix = value[:16]
        with session_factory() as session:
            record = APIKeyModel(
                name=name,
                key_prefix=prefix,
                key_hash=_hash_with_salt(value, salt),
                salt=salt,
                scopes=",".join(scopes),
                is_active=True,
                created_at=now,
                rotation_hint="",
            )
            session.add(record)
            session.commit()
            session.refresh(record)
        observability.emit(
            level=observability.logger.level,
            msg="کلید جدید ایجاد شد",
            key_prefix=prefix,
            operator_id=getattr(request.state, "operator_id", "ops"),
        )
        payload = {
            "message_fa": "کلید با موفقیت ایجاد شد",
            "value": value,
            "key": _serialize(record),
        }
        return _response(payload)

    @router.post("/api-keys/{key_id}/disable")
    async def disable_key(key_id: int, request: Request, token: None = Depends(_require_token)) -> JSONResponse:  # type: ignore[assignment]
        with session_factory() as session:
            record = session.get(APIKeyModel, key_id)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "VALIDATION_ERROR", "message_fa": "کلید یافت نشد"},
                )
            record.is_active = False
            record.disabled_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()
            session.refresh(record)
        observability.emit(
            level=observability.logger.level,
            msg="کلید غیرفعال شد",
            key_prefix=record.key_prefix,
            operator_id=getattr(request.state, "operator_id", "ops"),
        )
        return _response({"message_fa": "کلید غیرفعال شد", "key": _serialize(record)})

    @router.post("/api-keys/{key_id}/rotate")
    async def rotate_key(key_id: int, request: Request, token: None = Depends(_require_token)) -> JSONResponse:  # type: ignore[assignment]
        body = await request.json()
        hint = str(body.get("hint") or "")
        with session_factory() as session:
            record = session.get(APIKeyModel, key_id)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "VALIDATION_ERROR", "message_fa": "کلید یافت نشد"},
                )
            new_value = secrets.token_urlsafe(40)
            new_salt = secrets.token_hex(16)
            record.key_prefix = new_value[:16]
            record.key_hash = _hash_with_salt(new_value, new_salt)
            record.salt = new_salt
            record.rotation_hint = hint
            record.last_used_at = None
            record.disabled_at = None
            record.is_active = True
            session.add(record)
            session.commit()
            session.refresh(record)
        observability.emit(
            level=observability.logger.level,
            msg="کلید چرخانده شد",
            key_prefix=record.key_prefix,
            operator_id=getattr(request.state, "operator_id", "ops"),
        )
        payload = {
            "message_fa": "کلید با موفقیت چرخانده شد",
            "value": new_value,
            "key": _serialize(record),
        }
        return _response(payload)

    @router.get("/diagnostics")
    async def diagnostics(request: Request, token: None = Depends(_require_token)) -> JSONResponse:  # type: ignore[assignment]
        registry = observability.registry
        rate_limits = _collect_metric(registry, "rate_limit_reject_total", "route")
        idempotency = _collect_metric(registry, "idempotency_cache_total", "outcome")
        started_at = getattr(request.app.state, "started_at", time.time())
        uptime = round(time.time() - started_at, 3)
        payload = {
            "message_fa": "گزارش سلامت سامانه",
            "rate_limits": rate_limits,
            "idempotency": idempotency,
            "runtime_extras": getattr(request.app.state, "runtime_extras", {}),
            "uptime_seconds": uptime,
        }
        return _response(payload)

    return router


def _hash_with_salt(value: str, salt: str) -> str:
    digest = hashlib.sha256()
    digest.update((salt + value).encode("utf-8"))
    return digest.hexdigest()


def _hash_operator(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"ops:{digest[:12]}"


def _collect_metric(registry, metric_name: str, label_key: str) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for metric in registry.collect():
        if metric.name != metric_name:
            continue
        for sample in metric.samples:
            label = sample.labels.get(label_key, "total")
            snapshot[label] = float(sample.value)
    return snapshot
