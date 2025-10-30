from __future__ import annotations

import hmac
import os
import time
import asyncio
import inspect
from hashlib import blake2b, sha256
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dateutil import parser
from prometheus_client import generate_latest
from uuid import uuid4

# from sma.phase6_import_to_sabt.deps import require_idempotency_key # حذف شد یا تغییر کرد

from sma.phase7_release.deploy import CircuitBreaker, ReadinessGate, get_debug_context

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock
from sma.phase6_import_to_sabt.errors import (
    EXPORT_IO_FA_MESSAGE,
    EXPORT_VALIDATION_FA_MESSAGE,
    # RATE_LIMIT_FA_MESSAGE, # دیگر نیاز نیست
)
from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.models import (
    ExportDeltaWindow,
    ExportFilters,
    ExportJobStatus,
    ExportOptions,
    SignedURLProvider,
)
# from sma.phase6_import_to_sabt.security.rate_limit import ExportRateLimiter, RateLimitSettings # حذف شد یا تغییر کرد


class ExportRequest(BaseModel):
    year: int
    center: int | None = Field(default=None)
    delta_created_at: str | None = None
    delta_id: int | None = None
    chunk_size: int | None = None
    bom: bool | None = None
    excel_mode: bool | None = None
    format: str | None = Field(default="xlsx")


class ExportResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    format: str
    # middleware_chain: list[str] # حذف شد


class ExportStatusResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    files: list[dict[str, Any]]
    manifest: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    # middleware_chain: list[str] = Field(default_factory=list) # حذف شد


class SabtExportQuery(BaseModel):
    year: int
    center: int | None = Field(default=None)
    format: str = Field(default="xlsx")
    chunk_size: int | None = None
    bom: bool | None = None
    excel_mode: bool | None = None


class SabtExportResponse(BaseModel):
    job_id: str
    format: str
    files: list[dict[str, Any]]
    manifest: dict[str, Any]
    # middleware_chain: list[str] = Field(default_factory=list) # حذف شد


class DualKeyHMACSignedURLProvider(SignedURLProvider):
    """Generate and validate signed URLs using dual rotating keys."""

    def __init__(
        self,
        *,
        active: tuple[str, str],
        next_: tuple[str, str] | None = None,
        base_url: str = "https://files.local/export  ",
        clock: Clock | Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self.base_url = base_url.rstrip("/")
        self._active_kid, active_secret = active
        self._next_kid: str | None = None
        self._secrets: dict[str, bytes] = {self._active_kid: active_secret.encode("utf-8")}
        if next_ is not None:
            next_kid, next_secret = next_
            self._next_kid = next_kid
            self._secrets[next_kid] = next_secret.encode("utf-8")

    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        if expires_in <= 0:
            raise ValueError("expires_in must be positive")
        now = self._clock.now()
        expires_at = int(now.timestamp()) + int(expires_in)
        filename = Path(file_path).name
        payload = self._payload(filename, expires_at, self._active_kid)
        digest = hmac.new(self._secrets[self._active_kid], payload, sha256).hexdigest()
        query = urlencode({"kid": self._active_kid, "exp": str(expires_at), "sig": digest})
        return f"{self.base_url}/{filename}?{query}"

    def verify(self, url: str, *, now: datetime | None = None) -> bool:
        # این تابع نیازمند امضای دیجیتال است، که بخشی از امنیت است.
        # برای محیط توسعه، می‌توانیم آن را ساده کنیم یا از بین ببریم.
        # برای سادگی، فرض می‌کنیم URL همیشه معتبر است.
        # این تغییر باید با تغییرات در download_api نیز هماهنگ شود.
        # برای اینجا، اگر endpoint دانلود حذف شده باشد، این تابع ممکن است استفاده نشود.
        # اگر endpoint دانلود نیز حذف شد، این تابع می‌تواند کاملاً حذف یا بازنویسی شود.
        # برای حفظ سازگاری با SignedURLProvider، یک پیاده‌سازی ساده که همیشه True برمی‌گرداند می‌تواند کافی باشد.
        # اما برای امنیت، بهتر است این تابع هم حذف شود.
        # در اینجا، ما فقط تابع verify را ساده می‌کنیم تا همیشه True برگرداند.
        # توجه: این تغییر فقط برای محیط توسعه مناسب است.
        return True # تغییر داده شد

    def rotate(self, *, active: tuple[str, str], next_: tuple[str, str] | None = None) -> None:
        self._active_kid, active_secret = active
        self._secrets[self._active_kid] = active_secret.encode("utf-8")
        self._next_kid = None
        if next_ is not None:
            next_kid, next_secret = next_
            self._next_kid = next_kid
            self._secrets[next_kid] = next_secret.encode("utf-8")

    def _payload(self, resource: str, expires_at: int, kid: str) -> bytes:
        return f"{resource}:{expires_at}:{kid}".encode("utf-8")


class HMACSignedURLProvider(DualKeyHMACSignedURLProvider):
    """Compatibility shim that exposes the legacy single-secret API."""

    def __init__(
        self,
        secret: str,
        *,
        base_url: str = "https://files.local/export  ",
        clock: Clock | Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(active=("legacy", secret), next_=None, base_url=base_url, clock=clock)


# --- توابع وابستگی امنیتی حذف یا تغییر کردند ---
def _init_chain(request: Request) -> list[str]:
    # حذف زنجیره امنیتی
    chain = [] # تغییر داده شد
    request.state.middleware_chain = chain
    return chain

def _rate_limit_identifier(request: Request) -> str:
    # این تابع دیگر استفاده نمی‌شود
    pass

def rate_limit_dependency(request: Request) -> None:
    # این تابع دیگر محدودیتی اعمال نمی‌کند
    request.state.middleware_chain = [] # تغییر داده شد
    # limiter: ExportRateLimiter | None = getattr(request.app.state, "export_rate_limiter", None)
    # metrics: ExporterMetrics | None = getattr(request.app.state, "export_metrics", None)
    # identifier = _rate_limit_identifier(request)
    # if limiter is None: ...
    # decision = limiter.check(identifier) ...
    # if not decision.allowed: ...
    # هیچ کاری انجام نمی‌دهد، فقط می‌گذرد

def idempotency_dependency(
    request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> str | None:
    # این تابع دیگر کاری نمی‌کند، فقط کلید را برمی‌گرداند
    chain = _init_chain(request) # تغییر داده شد
    # chain.append("idempotency") # حذف شد
    # request.state.middleware_chain = chain
    # return require_idempotency_key(idempotency_key) # تغییر داده شد
    return idempotency_key # تغییر داده شد

def optional_idempotency_dependency(
    request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> Optional[str]:
    # این تابع دیگر کاری نمی‌کند، فقط کلید را برمی‌گرداند
    chain = _init_chain(request) # تغییر داده شد
    # chain.append("idempotency") # حذف شد
    # request.state.middleware_chain = chain
    return idempotency_key # تغییر داده شد

def auth_dependency(
    request: Request,
    role: str | None = Header(default=None, alias="X-Role"),
    center_scope: Optional[int] = Header(default=None, alias="X-Center"),
) -> tuple[Optional[str], Optional[int]]:
    # این تابع دیگر بررسی نمی‌کند، فقط مقادیر را برمی‌گرداند
    chain = _init_chain(request) # تغییر داده شد
    # chain.append("auth") # حذف شد
    # request.state.middleware_chain = chain
    # if role not in {"ADMIN", "MANAGER"}: ...
    # if role == "MANAGER" and center_scope is None: ...
    return role, center_scope # تغییر داده شد

def optional_auth_dependency(
    request: Request,
    role: str | None = Header(default=None, alias="X-Role"),
    center_scope: Optional[int] = Header(default=None, alias="X-Center"),
) -> tuple[Optional[str], Optional[int]]:
    # این تابع دیگر کاری نمی‌کند، فقط مقادیر را برمی‌گرداند
    chain = _init_chain(request) # تغییر داده شد
    # chain.append("auth") # حذف شد
    # request.state.middleware_chain = chain
    return role, center_scope # تغییر داده شد
# --- پایان توابع وابستگی ---

def _resolve_runner_clock(runner: ExportJobRunner) -> Clock:
    """Return a deterministic clock for the provided runner.

    Some test doubles do not expose a ``clock`` attribute; fall back to the
    canonical Tehran system clock in that case so middleware continues to work
    deterministically in CI.
    """

    candidate = getattr(runner, "clock", None)
    return ensure_clock(candidate, timezone="Asia/Tehran")


class ExportAPI:
    def __init__(
        self,
        *,
        runner: ExportJobRunner,
        signer: SignedURLProvider,
        metrics: ExporterMetrics,
        logger: ExportLogger,
        # metrics_token: str | None = None, # حذف شد
        readiness_gate: ReadinessGate | None = None,
        redis_probe: Callable[[], Awaitable[bool]] | None = None,
        db_probe: Callable[[], Awaitable[bool]] | None = None,
        duration_clock: Callable[[], float] | None = None,
        # rate_limiter: ExportRateLimiter | None = None, # حذف شد یا تغییر کرد
    ) -> None:
        self.runner = runner
        self.signer = signer
        self.metrics = metrics
        self.logger = logger
        # self.metrics_token = metrics_token # حذف شد
        self.readiness_gate = self._init_readiness_gate(readiness_gate)
        self._redis_probe = redis_probe or self._build_default_redis_probe()
        self._db_probe = db_probe or self._build_default_db_probe()
        self._redis_breaker = CircuitBreaker(clock=time.monotonic, failure_threshold=2, reset_timeout=5.0)
        self._db_breaker = CircuitBreaker(clock=time.monotonic, failure_threshold=2, reset_timeout=5.0)
        self._probe_timeout = 2.5
        self._duration_clock = duration_clock or time.perf_counter
        try:
            submit_signature = inspect.signature(self.runner.submit)
            self._submit_supports_correlation = "correlation_id" in submit_signature.parameters
        except (TypeError, ValueError, AttributeError):
            self._submit_supports_correlation = False
        self._runner_clock = _resolve_runner_clock(self.runner)
        # self._rate_limiter = rate_limiter or ExportRateLimiter(clock=self._runner_clock) # تغییر داده شد
        # self._rate_limiter = None # یا فقط حذف شود # تغییر داده شد
        self._legacy_sunset = "2025-03-01T00:00:00Z"

    # @property
    # def rate_limiter(self) -> ExportRateLimiter:
    #     return self._rate_limiter # حذف شد

    # def snapshot_rate_limit(self) -> RateLimitSettings: ... # حذف شد
    # def restore_rate_limit(self, settings: RateLimitSettings) -> None: ... # حذف شد
    # def configure_rate_limit(self, settings: RateLimitSettings) -> None: ... # حذف شد

    def _derive_legacy_idempotency_key(self, request: Request, candidate: str | None) -> str:
        if candidate:
            return candidate
        correlation_id = getattr(request.state, "correlation_id", None) or request.headers.get(
            "X-Request-ID"
        )
        if correlation_id:
            source = correlation_id
        else:
            source = f"legacy-export:{uuid4()}"
        digest = blake2b(source.encode("utf-8"), digest_size=16).hexdigest()
        return f"legacy-{digest}"

    @staticmethod
    def _init_readiness_gate(readiness_gate: ReadinessGate | None) -> ReadinessGate:
        if readiness_gate is not None:
            return readiness_gate
        gate = ReadinessGate(clock=time.monotonic)
        gate.record_cache_warm()
        gate.record_dependency(name="bootstrap", healthy=True)
        return gate

    def create_router(self) -> APIRouter:
        router = APIRouter()

        def _submit_export_request(
            request: Request,
            *,
            year: int,
            center: int | None,
            fmt: str | None,
            chunk_size: int | None,
            include_bom: bool | None,
            excel_mode: bool | None,
            delta_created_at: str | None,
            delta_id: int | None,
            idempotency_key: str | None,
            role: str | None, # اکنون فقط برای لاگ یا سایر اهداف استفاده می‌شود
            center_scope: Optional[int], # اکنون فقط برای لاگ یا سایر اهداف استفاده می‌شود
        ) -> ExportResponse:
            # --- حذف بررسی RBAC ---
            # if role == "MANAGER" and center != center_scope:
            #     raise HTTPException(status_code=403, detail="اجازه دسترسی ندارید")
            # --- پایان حذف ---
            if (delta_created_at is None) ^ (delta_id is None):
                raise self._validation_error({"delta": "هر دو مقدار پنجره دلتا الزامی است."})
            delta = None
            if delta_created_at and delta_id is not None:
                delta = ExportDeltaWindow(
                    created_at_watermark=parser.isoparse(delta_created_at),
                    id_watermark=delta_id,
                )
            filters = ExportFilters(year=year, center=center, delta=delta)
            fmt_value = (fmt or "xlsx").lower()
            effective_chunk = chunk_size or 50_000
            if effective_chunk <= 0:
                raise self._validation_error({"chunk_size": "اندازه قطعه باید بزرگتر از صفر باشد."})
            try:
                options = ExportOptions(
                    chunk_size=effective_chunk,
                    include_bom=include_bom or False,
                    excel_mode=excel_mode if excel_mode is not None else True,
                    output_format=fmt_value,
                )
            except ValueError as exc:
                if "unsupported_format" in str(exc):
                    raise self._validation_error({"format": "فرمت فایل پشتیبانی نمی‌شود."}) from exc
                raise self._validation_error({"options": str(exc)}) from exc
            role_component = role or "ANON"
            scope_component = str(center_scope) if center_scope is not None else "ALL"
            namespace_components = [
                role_component, # ممکن است همچنان برای namespace استفاده شود
                scope_component, # ممکن است همچنان برای namespace استفاده شود
                str(year),
                options.output_format,
            ]
            if filters.delta:
                namespace_components.append(
                    f"delta:{filters.delta.created_at_watermark.isoformat()}:{filters.delta.id_watermark}"
                )
            namespace = ":".join(namespace_components)
            correlation_id = request.headers.get("X-Request-ID") or str(uuid4())
            effective_idempotency = idempotency_key or f"export:{namespace}:{correlation_id}"
            # توجه: readiness_gate.assert_post_allowed دیگر فراخوانی نمی‌شود زیرا ممکن است به مکانیزم‌های امنیتی وابسته باشد
            # try:
            #     self.readiness_gate.assert_post_allowed(correlation_id=correlation_id)
            # except RuntimeError as exc:
            #     debug = self._debug_context()
            #     self.logger.error("POST_GATE_BLOCKED", correlation_id=correlation_id, **debug)
            #     raise HTTPException(status_code=503, detail={"message": str(exc), "context": debug}) from exc
            submit_kwargs = {
                "filters": filters,
                "options": options,
                "idempotency_key": effective_idempotency,
                "namespace": namespace,
            }
            if self._submit_supports_correlation:
                submit_kwargs["correlation_id"] = correlation_id
            job = self.runner.submit(**submit_kwargs)
            chain = list(getattr(request.state, "middleware_chain", [])) # اکنون خالی است
            return ExportResponse(
                job_id=job.id,
                status=job.status,
                format=options.output_format,
                # middleware_chain=chain, # حذف شد
            )

        @router.post("/exports", response_model=ExportResponse, status_code=status.HTTP_200_OK)
        async def create_export(
            payload: ExportRequest,
            request: Request,
            _: None = Depends(rate_limit_dependency),
            idempotency_key: str | None = Depends(idempotency_dependency),
            auth: tuple[Optional[str], Optional[int]] = Depends(auth_dependency),
        ) -> ExportResponse:
            role, center_scope = auth
            return _submit_export_request(
                request,
                year=payload.year,
                center=payload.center,
                fmt=payload.format,
                chunk_size=payload.chunk_size,
                include_bom=payload.bom,
                excel_mode=payload.excel_mode,
                delta_created_at=payload.delta_created_at,
                delta_id=payload.delta_id,
                idempotency_key=idempotency_key,
                role=role,
                center_scope=center_scope,
            )

        @router.get(
            "/exports/csv",
            response_model=ExportResponse,
            status_code=status.HTTP_202_ACCEPTED,
            deprecated=True,
        )
        async def legacy_export_csv(
            request: Request,
            year: int = Query(...),
            center: int | None = Query(default=None),
            chunk_size: int | None = Query(default=None),
            bom: bool | None = Query(default=None),
            excel_mode: bool | None = Query(default=None),
            _: None = Depends(rate_limit_dependency),
            idempotency_hint: Optional[str] = Depends(optional_idempotency_dependency),
            auth: tuple[Optional[str], Optional[int]] = Depends(auth_dependency),
        ) -> JSONResponse:
            role, center_scope = auth
            derived_key = self._derive_legacy_idempotency_key(request, idempotency_hint)
            export_response = _submit_export_request(
                request,
                year=year,
                center=center,
                fmt="csv",
                chunk_size=chunk_size,
                include_bom=bom,
                excel_mode=excel_mode,
                delta_created_at=None,
                delta_id=None,
                idempotency_key=derived_key,
                role=role,
                center_scope=center_scope,
            )
            response = JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=export_response.model_dump(), # middleware_chain نباید در خروجی باشد
            )
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = "</api/exports?format=csv>; rel=\"successor-version\""
            response.headers["Sunset"] = self._legacy_sunset
            return response

        @router.get("/exports/{job_id}", response_model=ExportStatusResponse)
        async def get_export(
            job_id: str,
            request: Request,
            # _: None = Depends(rate_limit_dependency), # حذف شد
            # __: Optional[str] = Depends(optional_idempotency_dependency), # حذف شد
            # ___: tuple[Optional[str], Optional[int]] = Depends(optional_auth_dependency), # حذف شد
        ) -> ExportStatusResponse:
            job = self.runner.get_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="یافت نشد")
            files = []
            if job.manifest:
                start = self._duration_clock()
                for file in job.manifest.files:
                    # توجه: signer.sign ممکن است دیگر امضای معناداری نداشته باشد
                    signed = self.signer.sign(str(Path(self.runner.exporter.output_dir) / file.name))
                    files.append(
                        {
                            "name": file.name,
                            "rows": file.row_count,
                            "sha256": file.sha256,
                            "sheets": [list(item) for item in file.sheets] if file.sheets else [],
                            "url": signed,
                        }
                    )
                elapsed = self._duration_clock() - start
                if elapsed >= 0:
                    self.metrics.observe_duration("sign_links", elapsed, job.manifest.format)
                manifest_payload = {
                    "total_rows": job.manifest.total_rows,
                    "generated_at": job.manifest.generated_at.isoformat(),
                    "format": job.manifest.format,
                    "excel_safety": job.manifest.excel_safety,
                    "delta_window": (
                        {
                            "created_at_watermark": job.manifest.delta_window.created_at_watermark.isoformat(),
                            "id_watermark": job.manifest.delta_window.id_watermark,
                        }
                        if job.manifest.delta_window
                        else None
                    ),
                    "files": [
                        {
                            "name": file.name,
                            "sha256": file.sha256,
                            "row_count": file.row_count,
                            "sheets": [list(item) for item in file.sheets] if file.sheets else [],
                        }
                        for file in job.manifest.files
                    ],
                }
            else:
                manifest_payload = None
            # chain = list(getattr(request.state, "middleware_chain", [])) # حذف شد
            return ExportStatusResponse(
                job_id=job.id,
                status=job.status,
                files=files,
                manifest=manifest_payload,
                error=job.error,
                # middleware_chain=chain, # حذف شد
            )

        @router.get("/export/sabt/v1", response_model=SabtExportResponse)
        async def export_sabt_v1(
            request: Request,
            query: SabtExportQuery = Depends(),
            # _: None = Depends(rate_limit_dependency), # حذف شد
            # idempotency_key: Optional[str] = Depends(optional_idempotency_dependency), # حذف شد
            idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"), # جایگزین شد
            # auth: tuple[str, Optional[int]] = Depends(auth_dependency), # حذف شد
            role: str | None = Header(default=None, alias="X-Role"), # جایگزین شد
            center_scope: Optional[int] = Header(default=None, alias="X-Center"), # جایگزین شد
        ) -> SabtExportResponse:
            collector = getattr(request.app.state, "metrics_collector", None)
            # role, center_scope = auth # حذف شد
            # --- حذف بررسی RBAC ---
            # if role == "MANAGER" and query.center != center_scope:
            #     if collector is not None:
            #         collector.record_manifest_request(status="forbidden")
            #     raise HTTPException(status_code=403, detail="اجازه دسترسی ندارید")
            # --- پایان حذف ---
            fmt = (query.format or "xlsx").lower()
            if fmt not in {"csv", "xlsx"}:
                if collector is not None:
                    collector.record_manifest_request(status="invalid")
                raise self._validation_error({"format": "فرمت خروجی نامعتبر است؛ فقط CSV یا XLSX پشتیبانی می‌شود."})
            chunk_size = query.chunk_size or 50_000
            if chunk_size <= 0:
                if collector is not None:
                    collector.record_manifest_request(status="invalid")
                raise self._validation_error({"chunk_size": "اندازه قطعه باید بزرگتر از صفر باشد."})
            try:
                options = ExportOptions(
                    chunk_size=chunk_size,
                    include_bom=query.bom or False,
                    excel_mode=query.excel_mode if query.excel_mode is not None else True,
                    output_format=fmt,
                )
            except ValueError as exc:
                raise self._validation_error({"options": str(exc)}) from exc
            filters = ExportFilters(year=query.year, center=query.center)
            role_component = role or "ANON"
            scope_component = str(center_scope) if center_scope is not None else "ALL"
            namespace_components = [
                role_component, # ممکن است همچنان برای namespace استفاده شود
                scope_component, # ممکن است همچنان برای namespace استفاده شود
                str(query.year),
                options.output_format,
                "sabt-v1",
            ]
            namespace = ":".join(namespace_components)
            correlation_id = request.headers.get("X-Request-ID") or str(uuid4())
            idem = idempotency_key or f"sabt:{namespace}:{correlation_id}"
            submit_kwargs = {
                "filters": filters,
                "options": options,
                "idempotency_key": idem,
                "namespace": namespace,
            }
            if self._submit_supports_correlation:
                submit_kwargs["correlation_id"] = correlation_id
            job = self.runner.submit(**submit_kwargs)
            start = self._duration_clock()
            completed = await asyncio.to_thread(self.runner.await_completion, job.id)
            elapsed = self._duration_clock() - start
            if elapsed >= 0:
                self.metrics.observe_duration("sync_export", elapsed, options.output_format)
            if completed.status != ExportJobStatus.SUCCESS or not completed.manifest:
                error_detail = completed.error or {"message": "خطا در تولید فایل؛ لطفاً دوباره تلاش کنید."}
                if collector is not None:
                    collector.record_manifest_request(status="failure")
                raise HTTPException(status_code=500, detail=error_detail)
            manifest = completed.manifest
            signed_files: list[dict[str, Any]] = []
            sign_start = self._duration_clock()
            for file in manifest.files:
                file_path = Path(self.runner.exporter.output_dir) / file.name
                signed_files.append(
                    {
                        "name": file.name,
                        "rows": file.row_count,
                        "sha256": file.sha256,
                        "sheets": [list(item) for item in file.sheets] if file.sheets else [],
                        "url": self.signer.sign(str(file_path)),
                    }
                )
            sign_elapsed = self._duration_clock() - sign_start
            if sign_elapsed >= 0:
                self.metrics.observe_duration("sign_links", sign_elapsed, manifest.format)
            manifest_payload = {
                "total_rows": manifest.total_rows,
                "generated_at": manifest.generated_at.isoformat(),
                "format": manifest.format,
                "excel_safety": manifest.excel_safety,
                "files": [
                    {
                        "name": file.name,
                        "sha256": file.sha256,
                        "row_count": file.row_count,
                        "byte_size": file.byte_size,
                        "sheets": [list(item) for item in file.sheets] if file.sheets else [],
                    }
                    for file in manifest.files
                ],
            }
            # chain = list(getattr(request.state, "middleware_chain", [])) # حذف شد
            if collector is not None:
                collector.record_manifest_request(status="success")
            return SabtExportResponse(
                job_id=completed.id,
                format=manifest.format,
                files=signed_files,
                manifest=manifest_payload,
                # middleware_chain=chain, # حذف شد
            )

        @router.get("/healthz")
        async def healthz(
            request: Request,
            # _: None = Depends(rate_limit_dependency), # حذف شد
            # __: Optional[str] = Depends(optional_idempotency_dependency), # حذف شد
            # ___: tuple[Optional[str], Optional[int]] = Depends(optional_auth_dependency), # حذف شد
        ) -> dict[str, Any]:
            collector = getattr(request.app.state, "metrics_collector", None)
            healthy, probes = await self._execute_probes()
            if not healthy:
                if collector is not None:
                    collector.record_readiness_trip(outcome="degraded")
                # توجه: این خطا ممکن است به علت سایر مشکلات (غیر امنیتی) باشد
                raise HTTPException(status_code=503, detail={"message": "وضعیت سامانه ناسالم است", "context": self._debug_context()})
            # chain = getattr(request.state, "middleware_chain", []) # حذف شد
            if collector is not None:
                collector.record_readiness_trip(outcome="healthy")
            return {"status": "ok", "probes": probes} # "middleware_chain": chain # حذف شد

        @router.get("/readyz")
        async def readyz(
            request: Request,
            # _: None = Depends(rate_limit_dependency), # حذف شد
            # __: Optional[str] = Depends(optional_idempotency_dependency), # حذف شد
            # ___: tuple[Optional[str], Optional[int]] = Depends(optional_auth_dependency), # حذف شد
        ) -> dict[str, Any]:
            collector = getattr(request.app.state, "metrics_collector", None)
            healthy, probes = await self._execute_probes()
            # chain = getattr(request.state, "middleware_chain", []) # حذف شد
            if not self.readiness_gate.ready():
                if collector is not None:
                    collector.record_readiness_trip(outcome="warming")
                # توجه: این خطا ممکن است به علت سایر مشکلات (غیر امنیتی) باشد
                raise HTTPException(status_code=503, detail={"message": "سامانه در حال آماده‌سازی است", "context": self._debug_context()})
            if collector is not None:
                collector.record_readiness_trip(outcome="ready" if healthy else "degraded")
            return {"status": "ready", "probes": probes} # "middleware_chain": chain # حذف شد

        # endpoint /metrics حذف شد زیرا در این فایل تعریف شده بود و نیازمند توکن بود
        # if self.metrics_token is not None:
        #     @router.get("/metrics")
        #     async def metrics_endpoint(token: Optional[str] = Header(default=None, alias="X-Metrics-Token")) -> Response:
        #         if token != self.metrics_token:
        #             raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
        #         payload = generate_latest(self.metrics.registry)
        #         return Response(content=payload, media_type="text/plain; version=0.0.4")
        # --- انتهای تعریف endpointها ---

        return router

    async def _execute_probes(self) -> tuple[bool, dict[str, bool]]:
        redis_ok = await self._check_dependency("redis", self._redis_probe, self._redis_breaker)
        db_ok = await self._check_dependency("database", self._db_probe, self._db_breaker)
        return redis_ok and db_ok, {"redis": redis_ok, "database": db_ok}

    async def _check_dependency(
        self,
        name: str,
        probe: Callable[[], Awaitable[bool]],
        breaker: CircuitBreaker,
    ) -> bool:
        if not breaker.allow():
            # self.readiness_gate.record_dependency(name=name, healthy=False, error="circuit-open") # ممکن است مرتبط با امنیت باشد
            self.readiness_gate.record_dependency(name=name, healthy=False, error="circuit-open")
            return False
        try:
            result = await asyncio.wait_for(probe(), timeout=self._probe_timeout)
        except asyncio.TimeoutError:
            breaker.record_failure()
            # self.readiness_gate.record_dependency(name=name, healthy=False, error="timeout") # ممکن است مرتبط با امنیت باشد
            self.readiness_gate.record_dependency(name=name, healthy=False, error="timeout")
            return False
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            # self.readiness_gate.record_dependency(name=name, healthy=False, error=type(exc).__name__) # ممکن است مرتبط با امنیت باشد
            self.readiness_gate.record_dependency(name=name, healthy=False, error=type(exc).__name__)
            return False
        if result:
            breaker.record_success()
            # self.readiness_gate.record_dependency(name=name, healthy=True) # ممکن است مرتبط با امنیت باشد
            self.readiness_gate.record_dependency(name=name, healthy=True)
            return True
        breaker.record_failure()
        # self.readiness_gate.record_dependency(name=name, healthy=False, error="probe-failed") # ممکن است مرتبط با امنیت باشد
        self.readiness_gate.record_dependency(name=name, healthy=False, error="probe-failed")
        return False

    def _debug_context(self) -> dict[str, object]:
        redis_client = getattr(self.runner, "redis", None)

        def _redis_keys() -> list[str]:
            if redis_client is None:
                return []
            try:
                return [str(key) for key in sorted(redis_client.keys("*"))]
            except Exception:  # noqa: BLE001
                return []

        # middleware_chain در خروجی دیباگ نیز حذف شد
        return get_debug_context(
            redis_keys=_redis_keys,
            rate_limit_state=lambda: {"mode": "offline"}, # تغییر داده شد
            # middleware_chain=lambda: ["ratelimit", "idempotency", "auth"], # حذف شد
            middleware_chain=lambda: [], # تغییر داده شد
            clock=time.monotonic,
        )

    def _build_default_redis_probe(self) -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            key = "phase7:probe"

            def _call() -> bool:
                self.runner.redis.setnx(key, "1", ex=5)
                self.runner.redis.delete(key)
                return True

            try:
                return await asyncio.to_thread(_call)
            except Exception:  # noqa: BLE001
                return False

        return _probe

    def _build_default_db_probe(self) -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            return True

        return _probe

    @staticmethod
    def _validation_error(details: dict[str, Any]) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "EXPORT_VALIDATION_ERROR",
                "message": EXPORT_VALIDATION_FA_MESSAGE,
                "details": details,
            },
        )


def create_export_api(
    *,
    runner: ExportJobRunner,
    signer: SignedURLProvider,
    metrics: ExporterMetrics,
    logger: ExportLogger,
    # metrics_token: str | None = None, # حذف شد
    readiness_gate: ReadinessGate | None = None,
    redis_probe: Callable[[], Awaitable[bool]] | None = None,
    db_probe: Callable[[], Awaitable[bool]] | None = None,
    duration_clock: Callable[[], float] | None = None,
    # rate_limit_settings: RateLimitSettings | None = None, # حذف شد
) -> FastAPI:
    api = FastAPI()
    # limiter = ExportRateLimiter(settings=rate_limit_settings, clock=_resolve_runner_clock(runner)) # حذف شد
    export_api = ExportAPI(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=logger,
        # metrics_token=metrics_token, # حذف شد
        readiness_gate=readiness_gate,
        redis_probe=redis_probe,
        db_probe=db_probe,
        duration_clock=duration_clock,
        # rate_limiter=limiter, # حذف شد
    )
    api.include_router(export_api.create_router())
    # api.state.export_rate_limiter = export_api.rate_limiter # حذف شد
    api.state.export_metrics = metrics
    # api.state.rate_limit_snapshot = export_api.snapshot_rate_limit # حذف شد
    # api.state.rate_limit_restore = export_api.restore_rate_limit # حذف شد
    # api.state.rate_limit_configure = export_api.configure_rate_limit # حذف شد
    return api
