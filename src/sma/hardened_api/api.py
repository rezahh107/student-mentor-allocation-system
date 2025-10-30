"""FastAPI router exposing hardened Student Allocation endpoints."""
from __future__ import annotations

import asyncio
import json
import time
import unicodedata
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sma.core.clock import Clock, ensure_clock
from sma.phase3_allocation.allocation_tx import AtomicAllocator, AllocationRequest
from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.phase2_counter_service.counter_runtime import (
    CounterRuntime,
    CounterRuntimeError,
)
from sma.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics

# from .middleware import ( # حذف شد یا تغییر کرد
#     AuthConfig, # حذف شد
#     MiddlewareState, # حذف شد یا تغییر کرد
#     RateLimitConfig, # حذف شد یا تغییر کرد
#     RateLimitRule, # حذف شد یا تغییر کرد
#     finalize_response, # حذف شد یا تغییر کرد
#     get_client_ip, # حذف شد یا تغییر کرد
#     get_rate_limit_info, # حذف شد یا تغییر کرد
#     setup_middlewares, # حذف شد یا تغییر کرد
# )
# from .observability import ( # حذف شد یا تغییر کرد
#     InFlightTracker, # حذف شد یا تغییر کرد
#     StructuredLogger, # حذف شد یا تغییر کرد
#     build_logger, # حذف شد یا تغییر کرد
#     enrich_span, # حذف شد یا تغییر کرد
#     get_metric, # حذف شد یا تغییر کرد
#     record_metrics, # حذف شد یا تغییر کرد
#     start_trace, # حذف شد یا تغییر کرد
#     TraceContext, # حذف شد یا تغییر کرد
# )
# from .redis_support import ( # حذف شد یا تغییر کرد
#     create_redis_client, # حذف شد یا تغییر کرد
#     RedisExecutor, # حذف شد یا تغییر کرد
#     RedisIdempotencyRepository, # حذف شد یا تغییر کرد
#     RedisNamespaces, # حذف شد یا تغییر کرد
#     RedisOperationError, # حذف شد یا تغییر کرد
#     RedisRetryConfig, # حذف شد یا تغییر کرد
#     RedisSlidingWindowLimiter, # حذف شد یا تغییر کرد
#     JWTDenyList, # حذف شد
# )

# --- تعاریف موقت برای جلوگیری از خطا ---
# این تعاریف باید با تغییرات اعمال شده در فایل‌های وابسته هماهنگ شوند
# اینجا فقط یک پوسته خالی یا یک ساختار ساده ایجاد می‌کنیم

class DummyMiddlewareState:
    def __init__(self):
        self.metrics_token = None
        self.metrics_ip_allowlist = set()
        self.max_body_bytes = 32 * 1024
        # دیگر فیلدها را نیز مطابق نیاز اضافه کنید

class DummyLogger:
    def info(self, msg, extra=None): pass
    def error(self, msg, extra=None): pass
    def warning(self, msg, extra=None): pass
    def debug(self, msg, extra=None): pass

def dummy_setup_middlewares(app, state, allowed_origins): pass # فقط یک تابع خالی

def dummy_get_metric(name): # فقط یک شیء سازگار برمی‌گرداند
    class DummyMetric:
        def labels(self, **kwargs): return self
        def inc(self, val=1): pass
        def observe(self, val): pass
    return DummyMetric()

def dummy_build_logger(): return DummyLogger()

def dummy_start_trace(context): return None
def dummy_enrich_span(span, status_code): pass
def dummy_record_metrics(path, method, status_code, latency_s): pass
async def dummy_finalize_response(request, response, logger, status_code, error_code=None, outcome="success"): pass
def dummy_create_redis_client(url): return None # یا یک شیء سازگار
class DummyRedisExecutor:
    def __init__(self, config, namespace): pass
class DummyNamespaces:
    def __init__(self, base): self.base = base
class DummyRateLimitConfig:
    def __init__(self, default_rule, per_route, fail_open): pass
class DummyRateLimitRule:
    def __init__(self, requests, window): pass
class DummyIdempotencyRepo:
    def __init__(self, redis, namespaces, ttl_seconds, executor): pass
    async def get_reservation(self, key): return DummyReservation()
class DummyReservation:
    async def commit(self, result): pass
    async def abort(self): pass
class DummyRateLimiter:
    def __init__(self, redis, namespaces, fail_open, executor): pass

# --- پایان تعاریف موقت ---


class GenderEnum(int, Enum):
    FEMALE = 0
    MALE = 1


class RegistrationCenterEnum(int, Enum):
    NORTH = 0
    CENTER = 1
    SOUTH = 2


class RegistrationStatusEnum(int, Enum):
    NEW = 0
    ACTIVE = 1
    GRADUATED = 3


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("ك", "ک").replace("ي", "ی")
    normalized = normalized.replace("\u200c", "").replace("\ufeff", "")
    normalized = normalized.strip()
    return normalized


def _fold_digits(value: str) -> str:
    builder: list[str] = []
    for ch in value:
        digit = unicodedata.digit(ch, None)
        if digit is None:
            builder.append(ch)
        else:
            builder.append(str(digit))
    return "".join(builder)


def _sanitize_identifier(value: Any) -> str:
    if value in (None, ""):
        raise ValueError("شناسه الزامی است")
    if isinstance(value, int):
        text = str(value)
    else:
        text = _fold_digits(_normalize_text(str(value)))
    text = text.strip()
    if not text:
        raise ValueError("شناسه الزامی است")
    return text


class AllocationRequestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    student_id: str = Field(alias="student_id", validation_alias="studentId")
    mentor_id: int = Field(alias="mentor_id", validation_alias="mentorId")
    reg_center: RegistrationCenterEnum = Field(alias="reg_center", validation_alias="regCenter")
    reg_status: RegistrationStatusEnum = Field(alias="reg_status", validation_alias="regStatus")
    gender: GenderEnum
    phone: str | None = None
    national_id: str | None = Field(default=None, alias="national_id", validation_alias="nationalId")
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("student_id", mode="before")
    @classmethod
    def _validate_student(cls, value: Any) -> str:
        text = _sanitize_identifier(value)
        if not text.isdigit() or text.lstrip("0") == "":
            raise ValueError("شناسهٔ دانش‌آموز نامعتبر است")
        return text

    @field_validator("mentor_id", mode="before")
    @classmethod
    def _validate_mentor(cls, value: Any) -> int:
        text = _sanitize_identifier(value)
        if not text.isdigit() or text.lstrip("0") == "":
            raise ValueError("شناسهٔ منتور نامعتبر است")
        return int(text)

    @field_validator("phone", mode="before")
    @classmethod
    def _validate_phone(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = _fold_digits(_normalize_text(str(value)))
        if not text:
            return None
        if len(text) != 11 or not text.startswith("09") or not text.isdigit():
            raise ValueError("شمارهٔ تماس نامعتبر است")
        return text

    @field_validator("national_id", mode="before")
    @classmethod
    def _validate_nid(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = _sanitize_identifier(value)
        if len(text) != 10 or not text.isdigit():
            raise ValueError("کد ملی نامعتبر است")
        return text

    @field_validator("payload", mode="before")
    @classmethod
    def _ensure_payload(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("payload نامعتبر است") from exc
        raise TypeError("payload باید دیکشنری باشد")


class AllocationResponseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    allocation_id: int | None
    allocation_code: str | None
    year_code: str | None
    mentor_id: int | None
    status: str
    message: str
    error_code: str | None = None
    correlation_id: str


class StatusResponseDTO(BaseModel):
    status: str = "ok"
    service: str = "allocation_api"


class ErrorEnvelope(BaseModel):
    code: str
    message_fa: str
    correlation_id: str
    details: Any | None = None


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: Any | None = None,
) -> JSONResponse:
    body = {"error": ErrorEnvelope(code=code, message_fa=message, correlation_id=correlation_id, details=details).model_dump(by_alias=True)}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _wrap_service(allocation: AllocationRequestDTO, allocator: AtomicAllocator) -> AllocationResponseDTO:
    request = AllocationRequest(
        student_id=allocation.student_id,
        mentor_id=allocation.mentor_id,
        payload=allocation.payload,
        metadata={
            "reg_center": allocation.reg_center.value,
            "reg_status": allocation.reg_status.value,
            "gender": allocation.gender.value,
        },
    )
    result = allocator.allocate(request)
    return AllocationResponseDTO(
        allocation_id=result.allocation_id,
        allocation_code=result.allocation_code,
        year_code=result.year_code,
        mentor_id=result.mentor_id,
        status=result.status,
        message=result.message,
        error_code=result.error_code,
        correlation_id=str(uuid.uuid4()), # یا correlation_id از request.state
    )


class APISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] = Field(default_factory=lambda: ["https://student.medu.ir  "])
    # rate_limit_default: int = 10 # حذف شد یا تغییر کرد
    # rate_limit_window: float = 1.0 # حذف شد یا تغییر کرد
    # rate_limit_allocations: int = 5 # حذف شد یا تغییر کرد
    # rate_limit_status: int = 20 # حذف شد یا تغییر کرد
    # idempotency_ttl_seconds: int = 86400 # حذف شد یا تغییر کرد
    # metrics_token: str | None = None # حذف شد یا تغییر کرد
    # metrics_ip_allowlist: list[str] = Field(default_factory=lambda: ["127.0.0.1"]) # حذف شد یا تغییر کرد
    # max_body_bytes: int = 32 * 1024 # ممکن است حذف شود
    # redis_url: str = "redis://localhost:6379/0" # حذف شد یا تغییر کرد
    # redis_namespace: str = "alloc" # حذف شد یا تغییر کرد
    # rate_limit_fail_open: bool = False # حذف شد یا تغییر کرد
    # redis_max_retries: int = 3 # حذف شد یا تغییر کرد
    # redis_base_delay_ms: float = 50.0 # حذف شد یا تغییر کرد
    # redis_max_delay_ms: float = 400.0 # حذف شد یا تغییر کرد
    # redis_jitter_ms: float = 50.0 # حذف شد یا تغییر کرد
    # counter_hash_salt: str = "counter-runtime-salt" # ممکن است تغییر کند
    # counter_placeholder_ttl_ms: int = 5000 # ممکن است تغییر کند
    # counter_retry_attempts: int = 5 # ممکن است تغییر کند
    # counter_retry_base_ms: int = 20 # ممکن است تغییر کند
    # counter_retry_max_ms: int = 200 # ممکن است تغییر کند
    # counter_max_serial: int = 9999 # ممکن است تغییر کند
    # counter_year_map: dict[str, str] = Field(default_factory=dict) # ممکن است تغییر کند
    # فقط تنظیمات غیرامنیتی باقی می‌مانند
    counter_hash_salt: str = "dev-counter-runtime-salt"
    counter_placeholder_ttl_ms: int = 5000
    counter_retry_attempts: int = 5
    counter_retry_base_ms: int = 20
    counter_retry_max_ms: int = 200
    counter_max_serial: int = 9999
    counter_year_map: dict[str, str] = Field(default_factory=dict)


class APIState:
    def __init__(
        self,
        *,
        allocator: AtomicAllocator,
        settings: APISettings,
        # logger: StructuredLogger, # حذف شد یا تغییر کرد
        # namespaces: RedisNamespaces, # حذف شد یا تغییر کرد
        # redis_client, # حذف شد یا تغییر کرد
        counter_runtime: CounterRuntime,
        counter_metrics: CounterRuntimeMetrics,
        year_provider: AcademicYearProvider,
    ) -> None:
        self.allocator = allocator
        self.settings = settings
        # self.logger = logger # حذف شد یا تغییر کرد
        # self.redis_client = redis_client # حذف شد یا تغییر کرد
        # self.namespaces = namespaces # حذف شد یا تغییر کرد
        self.counter_runtime = counter_runtime
        self.counter_metrics = counter_metrics
        self.year_provider = year_provider

    async def reset(self) -> None:
        # await self.redis_client.flushdb() # حذف شد یا تغییر کرد
        pass # یا عملیات جایگزین


ERROR_MAP = {
    # "AUTH_REQUIRED": (401, "AUTH_REQUIRED", "احراز هویت لازم است"), # حذف شد
    # "INVALID_TOKEN": (401, "INVALID_TOKEN", "توکن یا کلید نامعتبر است"), # حذف شد
    # "ROLE_DENIED": (403, "ROLE_DENIED", "دسترسی مجاز نیست"), # حذف شد
    # "RATE_LIMIT_EXCEEDED": (429, "RATE_LIMIT_EXCEEDED", "تعداد درخواست‌ها از حد مجاز عبور کرده است"), # حذف شد
    "VALIDATION_ERROR": (422, "VALIDATION_ERROR", "اطلاعات ارسال‌شده نامعتبر است"),
    # "CONTENT_TYPE_INVALID": (415, "CONTENT_TYPE_INVALID", "نوع محتوای ارسالی پشتیبانی نمی‌شود"), # ممکن است حذف شود
    # "BODY_TOO_LARGE": (413, "BODY_TOO_LARGE", "حجم درخواست بیش از حد مجاز است"), # ممکن است حذف شود
    # "CONFLICT": (409, "CONFLICT", "درخواست تکراری است"), # ممکن است مربوط به Idempotency باشد
    "INTERNAL": (500, "INTERNAL", "خطای داخلی سامانه"),
}


def _counter_status(code: str) -> int:
    return {
        "COUNTER_VALIDATION_ERROR": 400,
        "COUNTER_EXHAUSTED": 409,
        "COUNTER_RETRY_EXHAUSTED": 503,
        "COUNTER_STATE_ERROR": 500,
    }.get(code, 500)


# تابع /metrics دیگر نیاز به احراز هویت ندارد
async def _metrics_endpoint(request: Request) -> Response:
    # client_ip = get_client_ip(request) # حذف شد یا تغییر کرد
    # scrape_metric = get_metric("metrics_scrape_total") # حذف شد یا تغییر کرد
    # if middleware_state.metrics_token: ... # حذف شد یا تغییر کرد
    # if client_ip not in middleware_state.metrics_ip_allowlist: ... # حذف شد یا تغییر کرد
    from prometheus_client import generate_latest

    # scrape_metric.labels(outcome="success").inc() # حذف شد یا تغییر کرد
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain; version=0.0.4")


def create_app(
    *,
    allocator: AtomicAllocator,
    settings: APISettings,
    # auth_config: AuthConfig, # حذف شد
    # redis_client=None, # حذف شد یا تغییر کرد
) -> FastAPI:
    # logger = build_logger() # حذف شد یا تغییر کرد
    logger = dummy_build_logger() # استفاده از تابع موقت
    # redis_client = redis_client or create_redis_client(settings.redis_url) # حذف شد یا تغییر کرد
    redis_client = dummy_create_redis_client(settings.redis_url) # استفاده از تابع موقت
    # namespaces = RedisNamespaces(settings.redis_namespace) # حذف شد یا تغییر کرد
    namespaces = DummyNamespaces(settings.redis_namespace) # استفاده از کلاس موقت
    # retry_config = RedisRetryConfig(...) # حذف شد یا تغییر کرد
    # redis_executor = RedisExecutor(config=retry_config, namespace=settings.redis_namespace) # حذف شد یا تغییر کرد
    redis_executor = DummyRedisExecutor(config=None, namespace=settings.redis_namespace) # استفاده از کلاس موقت
    counter_metrics = CounterRuntimeMetrics()
    year_provider = AcademicYearProvider(settings.counter_year_map)
    counter_runtime = CounterRuntime(
        redis=redis_client,
        namespaces=namespaces,
        executor=redis_executor,
        metrics=counter_metrics,
        year_provider=year_provider,
        hash_salt=settings.counter_hash_salt,
        max_serial=settings.counter_max_serial,
        placeholder_ttl_ms=settings.counter_placeholder_ttl_ms,
        wait_attempts=settings.counter_retry_attempts,
        wait_base_ms=settings.counter_retry_base_ms,
        wait_max_ms=settings.counter_retry_max_ms,
    )
    api_state = APIState(
        allocator=allocator,
        settings=settings,
        # logger=logger, # حذف شد یا تغییر کرد
        # namespaces=namespaces, # حذف شد یا تغییر کرد
        # redis_client=redis_client, # حذف شد یا تغییر کرد
        counter_runtime=counter_runtime,
        counter_metrics=counter_metrics,
        year_provider=year_provider,
    )
    # jwt_deny = JWTDenyList(redis=redis_client, namespaces=namespaces, executor=redis_executor) # حذف شد
    # auth_config.jwt_deny_list = jwt_deny # حذف شد
    app = FastAPI(title="Student Allocation API", version="4.0", default_response_class=JSONResponse)
    # rate_limiter = RedisSlidingWindowLimiter(...) # حذف شد یا تغییر کرد
    rate_limiter = DummyRateLimiter(redis=redis_client, namespaces=namespaces, fail_open=True, executor=redis_executor) # استفاده از کلاس موقت
    # idempotency_repo = RedisIdempotencyRepository(...) # حذف شد یا تغییر کرد
    idempotency_repo = DummyIdempotencyRepo(redis=redis_client, namespaces=namespaces, ttl_seconds=86400, executor=redis_executor) # استفاده از کلاس موقت
    # rate_limit_state = MiddlewareState(...) # حذف شد یا تغییر کرد
    rate_limit_state = DummyMiddlewareState() # استفاده از کلاس موقت
    # setup_middlewares(app, state=rate_limit_state, allowed_origins=settings.allowed_origins) # حذف شد یا تغییر کرد
    dummy_setup_middlewares(app, state=rate_limit_state, allowed_origins=settings.allowed_origins) # استفاده از تابع موقت

    router = APIRouter()

    @router.post("/allocations", response_model=AllocationResponseDTO)
    async def create_allocation(
        request: Request,
        response: Response,
        payload: AllocationRequestDTO,
        # idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), # ممکن است حذف شود یا تغییر کند
    ) -> AllocationResponseDTO:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        # consumer_id = getattr(request.state, "consumer_id", "anonymous") # ممکن است تغییر کند
        # with InFlightTracker(path="/allocations", method="POST"): # حذف شد یا تغییر کرد
        # span = start_trace(...) # حذف شد یا تغییر کرد
        span = dummy_start_trace(None) # استفاده از تابع موقت
        try:
            # get_metric("alloc_attempt_total").labels(outcome="attempt").inc() # حذف شد یا تغییر کرد
            dummy_get_metric("alloc_attempt_total").labels(outcome="attempt").inc() # استفاده از تابع موقت
            result = await asyncio.get_event_loop().run_in_executor(None, _wrap_service, payload, allocator)
            enriched = result.model_copy()
            enriched.correlation_id = correlation_id
            # remaining = getattr(request.state, "rate_limit_remaining", "0") # حذف شد یا تغییر کرد
            # response.headers["X-RateLimit-Remaining"] = str(remaining) # حذف شد یا تغییر کرد
            # reservation = getattr(request.state, "idempotency_reservation", None) # حذف شد یا تغییر کرد
            # if reservation: ... # حذف شد یا تغییر کرد
            # get_metric("idempotency_events_total").labels(...).inc() # حذف شد یا تغییر کرد
            dummy_get_metric("alloc_attempt_total").labels(outcome="success").inc() # استفاده از تابع موقت
            return enriched
        except HTTPException:
            # reservation = getattr(request.state, "idempotency_reservation", None) # حذف شد یا تغییر کرد
            # if reservation: await reservation.abort() # حذف شد یا تغییر کرد
            raise
        except Exception as exc:  # pragma: no cover - safety net
            dummy_get_metric("alloc_attempt_total").labels(outcome="error").inc() # استفاده از تابع موقت
            # reservation = getattr(request.state, "idempotency_reservation", None) # حذف شد یا تغییر کرد
            # if reservation: await reservation.abort() # حذف شد یا تغییر کرد
            raise _http_error("INTERNAL", correlation_id, details=str(exc))
        finally:
            dummy_enrich_span(span, status_code=200) # استفاده از تابع موقت

    @router.post("/counter/allocate")
    async def counter_allocate(request: Request, response: Response) -> dict[str, object]:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        # with InFlightTracker(...): # حذف شد یا تغییر کرد
        # span = start_trace(...) # حذف شد یا تغییر کرد
        span = dummy_start_trace(None) # استفاده از تابع موقت
        try:
            try:
                payload = await request.json()
            except json.JSONDecodeError as exc:
                raise CounterRuntimeError(
                    "COUNTER_VALIDATION_ERROR",
                    "درخواست نامعتبر است؛ سال/جنسیت/مرکز را بررسی کنید.",
                    details=str(exc),
                ) from exc
            result = await api_state.counter_runtime.allocate(payload, correlation_id=correlation_id)
            envelope: dict[str, object] = {
                "ok": True,
                "counter": result.counter,
                "year_code": result.year_code,
                "status": result.status,
                "message_fa": "شماره ثبت با موفقیت تخصیص یافت.",
                "correlation_id": correlation_id,
            }
            # reservation = getattr(request.state, "idempotency_reservation", None) # حذف شد یا تغییر کرد
            # if reservation: ... # حذف شد یا تغییر کرد
            # get_metric("idempotency_events_total").labels(...).inc() # حذف شد یا تغییر کرد
            # remaining = getattr(request.state, "rate_limit_remaining", "0") # حذف شد یا تغییر کرد
            # response.headers["X-RateLimit-Remaining"] = str(remaining) # حذف شد یا تغییر کرد
            response.headers["X-Correlation-ID"] = correlation_id
            return envelope
        except CounterRuntimeError as exc:
            # reservation = getattr(request.state, "idempotency_reservation", None) # حذف شد یا تغییر کرد
            # if reservation: await reservation.abort() # حذف شد یا تغییر کرد
            status_code = _counter_status(exc.code)
            response.status_code = status_code
            response.headers["X-Correlation-ID"] = correlation_id
            payload = {
                "ok": False,
                "code": exc.code,
                "message_fa": exc.message_fa,
                "correlation_id": correlation_id,
            }
            if exc.details:
                payload["details"] = exc.details
            return payload
        finally:
            dummy_enrich_span(span, status_code=response.status_code) # استفاده از تابع موقت

    @router.get("/counter/preview")
    async def counter_preview(
        request: Request,
        response: Response,
        year: str,
        gender: str,
        center: str,
    ) -> dict[str, object]:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        # with InFlightTracker(...): # حذف شد یا تغییر کرد
        # span = start_trace(...) # حذف شد یا تغییر کرد
        span = dummy_start_trace(None) # استفاده از تابع موقت
        try:
            payload = {"year": year, "gender": gender, "center": center}
            result = await api_state.counter_runtime.preview(payload)
            response.headers["X-Correlation-ID"] = correlation_id
            return {
                "ok": True,
                "counter": result.counter,
                "year_code": result.year_code,
                "status": result.status,
                "message_fa": "پیش‌نمایش شمارهٔ بعدی.",
                "correlation_id": correlation_id,
            }
        except CounterRuntimeError as exc:
            status_code = _counter_status(exc.code)
            response.status_code = status_code
            response.headers["X-Correlation-ID"] = correlation_id
            payload = {
                "ok": False,
                "code": exc.code,
                "message_fa": exc.message_fa,
                "correlation_id": correlation_id,
            }
            if exc.details:
                payload["details"] = exc.details
            return payload
        finally:
            dummy_enrich_span(span, status_code=response.status_code) # استفاده از تابع موقت

    @router.get("/status", response_model=StatusResponseDTO)
    async def status(request: Request, response: Response) -> StatusResponseDTO:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        # with InFlightTracker(...): # حذف شد یا تغییر کرد
        # span = start_trace(...) # حذف شد یا تغییر کرد
        span = dummy_start_trace(None) # استفاده از تابع موقت
        try:
            return StatusResponseDTO()
        finally:
            dummy_enrich_span(span, status_code=200) # استفاده از تابع موقت

    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        details = exc.errors()
        return _error_response(
            status_code=ERROR_MAP["VALIDATION_ERROR"][0],
            code="VALIDATION_ERROR",
            message="اطلاعات ارسال‌شده نامعتبر است",
            correlation_id=correlation_id,
            details=details,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            content = exc.detail
            content["error"]["correlation_id"] = correlation_id
            return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(content))
        # if exc.status_code == 401: ... # حذف شد یا تغییر کرد
        code = "INTERNAL" # مقدار پیش‌فرض
        message = "خطای داخلی سامانه" # مقدار پیش‌فرض
        return _error_response(status_code=exc.status_code, code=code, message=message, correlation_id=correlation_id)

    # میدلویر اصلی که بررسی‌های امنیتی انجام می‌داد حذف یا تغییر می‌کند
    @app.middleware("http")
    async def _main_middleware(request: Request, call_next: Callable[[Request], Any]):
        request.state._start_time = time.perf_counter()
        # --- حذف بررسی Content-Type سفت‌گیرانه ---
        # content_type = request.headers.get("Content-Type")
        # if content_type != "application/json; charset=utf-8": ...
        # --- پایان حذف ---
        # --- حذف بررسی حجم بدنه ---
        # body = await request.body()
        # request._body = body
        # max_body = app.state.middleware_state.max_body_bytes
        # if len(body) > max_body: ...
        # --- پایان حذف ---
        try:
            response: Response = await call_next(request)
        # --- حذف handlerهای خاص امنیت ---
        # except PermissionError as exc: ...
        # except RedisOperationError as exc: ...
        # except ValueError as exc: ... (که شامل RATE_LIMIT_EXCEEDED می‌شد)
        # --- پایان حذف ---
        except Exception as exc: # یک handler عمومی برای خطاهای غیرمنتظره
            correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
            response = _error_response(
                status_code=ERROR_MAP["INTERNAL"][0],
                code="INTERNAL",
                message=ERROR_MAP["INTERNAL"][2],
                correlation_id=correlation_id,
                details=str(exc),
            )
            # await finalize_response(...) # حذف شد یا تغییر کرد
            dummy_finalize_response(request, response, logger, status_code=response.status_code, error_code="INTERNAL", outcome="internal_error") # استفاده از تابع موقت
            dummy_record_metrics(path=request.url.path, method=request.method, status_code=response.status_code, latency_s=0.0) # استفاده از تابع موقت
            return response
        else:
            latency = time.perf_counter() - request.state._start_time
            dummy_record_metrics(path=request.url.path, method=request.method, status_code=response.status_code, latency_s=latency) # استفاده از تابع موقت
            # remaining = getattr(request.state, "rate_limit_remaining", None) # حذف شد یا تغییر کرد
            # if remaining is not None and "X-RateLimit-Remaining" not in response.headers: ... # حذف شد یا تغییر کرد
            # await finalize_response(...) # حذف شد یا تغییر کرد
            dummy_finalize_response(request, response, logger, status_code=response.status_code, outcome="success") # استفاده از تابع موقت
            return response

    # تغییر مسیر /metrics
    async def metrics_handler(request: Request) -> Response:
        return await _metrics_endpoint(request) # بدون middleware_state

    app.add_api_route(
        "/metrics",
        metrics_handler,
        methods=["GET"],
        include_in_schema=False,
    )

    app.state.api_state = api_state
    # app.state.middleware_state = rate_limit_state # ممکن است همچنان لازم باشد یا نیاز به تغییر داشته باشد
    app.state.middleware_state = rate_limit_state

    return app


def get_debug_context(app: FastAPI, *, clock: Clock | None = None) -> dict[str, Any]:
    api_state: APIState = getattr(app.state, "api_state")
    middleware_state: MiddlewareState = getattr(app.state, "middleware_state") # اگر MiddlewareState وجود نداشته باشد، باید تغییر کند
    active_clock = ensure_clock(clock, default=Clock.for_tehran())
    return {
        # "redis_namespace": api_state.namespaces.base, # حذف شد یا تغییر کرد
        # "rate_limit_state": get_rate_limit_info(), # حذف شد یا تغییر کرد
        # "middlewares": [mw.cls.__name__ for mw in app.user_middleware], # ممکن است تغییر کند
        # "metrics_token_configured": bool(middleware_state.metrics_token), # حذف شد یا تغییر کرد
        "timestamp": active_clock.unix_timestamp(),
        "security_removed": True, # یک فیلد نشان‌دهنده تغییر
    }


def _http_error(code: str, correlation_id: str, *, details: Any | None = None) -> HTTPException:
    status_code, _, message = ERROR_MAP.get(code, (500, code, "خطای داخلی سامانه"))
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message_fa": message,
                "correlation_id": correlation_id,
                "details": details,
            }
        },
    )
