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

from src.phase3_allocation.allocation_tx import AtomicAllocator, AllocationRequest
from src.phase2_counter_service.academic_year import AcademicYearProvider
from src.phase2_counter_service.counter_runtime import (
    CounterRuntime,
    CounterRuntimeError,
)
from src.phase2_counter_service.runtime_metrics import CounterRuntimeMetrics

from .middleware import (
    AuthConfig,
    MiddlewareState,
    RateLimitConfig,
    RateLimitRule,
    finalize_response,
    get_client_ip,
    get_rate_limit_info,
    setup_middlewares,
)
from .observability import (
    InFlightTracker,
    StructuredLogger,
    build_logger,
    enrich_span,
    get_metric,
    record_metrics,
    start_trace,
    TraceContext,
)
from .redis_support import (
    create_redis_client,
    RedisExecutor,
    RedisIdempotencyRepository,
    RedisNamespaces,
    RedisOperationError,
    RedisRetryConfig,
    RedisSlidingWindowLimiter,
    JWTDenyList,
)


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
        correlation_id=str(uuid.uuid4()),
    )


class APISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] = Field(default_factory=lambda: ["https://student.medu.ir"])
    rate_limit_default: int = 10
    rate_limit_window: float = 1.0
    rate_limit_allocations: int = 5
    rate_limit_status: int = 20
    idempotency_ttl_seconds: int = 86400
    metrics_token: str | None = None
    metrics_ip_allowlist: list[str] = Field(default_factory=lambda: ["127.0.0.1"])
    max_body_bytes: int = 32 * 1024
    redis_url: str = "redis://localhost:6379/0"
    redis_namespace: str = "alloc"
    rate_limit_fail_open: bool = False
    redis_max_retries: int = 3
    redis_base_delay_ms: float = 50.0
    redis_max_delay_ms: float = 400.0
    redis_jitter_ms: float = 50.0
    counter_hash_salt: str = "counter-runtime-salt"
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
        logger: StructuredLogger,
        namespaces: RedisNamespaces,
        redis_client,
        counter_runtime: CounterRuntime,
        counter_metrics: CounterRuntimeMetrics,
        year_provider: AcademicYearProvider,
    ) -> None:
        self.allocator = allocator
        self.settings = settings
        self.logger = logger
        self.redis_client = redis_client
        self.namespaces = namespaces
        self.counter_runtime = counter_runtime
        self.counter_metrics = counter_metrics
        self.year_provider = year_provider

    async def reset(self) -> None:
        await self.redis_client.flushdb()


ERROR_MAP = {
    "AUTH_REQUIRED": (401, "AUTH_REQUIRED", "احراز هویت لازم است"),
    "INVALID_TOKEN": (401, "INVALID_TOKEN", "توکن یا کلید نامعتبر است"),
    "ROLE_DENIED": (403, "ROLE_DENIED", "دسترسی مجاز نیست"),
    "RATE_LIMIT_EXCEEDED": (429, "RATE_LIMIT_EXCEEDED", "تعداد درخواست‌ها از حد مجاز عبور کرده است"),
    "VALIDATION_ERROR": (422, "VALIDATION_ERROR", "اطلاعات ارسال‌شده نامعتبر است"),
    "CONTENT_TYPE_INVALID": (415, "CONTENT_TYPE_INVALID", "نوع محتوای ارسالی پشتیبانی نمی‌شود"),
    "BODY_TOO_LARGE": (413, "BODY_TOO_LARGE", "حجم درخواست بیش از حد مجاز است"),
    "CONFLICT": (409, "CONFLICT", "درخواست تکراری است"),
    "INTERNAL": (500, "INTERNAL", "خطای داخلی سامانه"),
}


def _counter_status(code: str) -> int:
    return {
        "COUNTER_VALIDATION_ERROR": 400,
        "COUNTER_EXHAUSTED": 409,
        "COUNTER_RETRY_EXHAUSTED": 503,
        "COUNTER_STATE_ERROR": 500,
    }.get(code, 500)


async def _metrics_endpoint(request: Request, state: APIState, middleware_state: MiddlewareState) -> Response:
    client_ip = get_client_ip(request)
    scrape_metric = get_metric("metrics_scrape_total")
    if middleware_state.metrics_token:
        header = request.headers.get("Authorization")
        if header != f"Bearer {middleware_state.metrics_token}":
            scrape_metric.labels(outcome="token_denied").inc()
            raise HTTPException(status_code=401, detail="metrics unauthorized")
    if client_ip not in middleware_state.metrics_ip_allowlist:
        scrape_metric.labels(outcome="ip_forbidden").inc()
        raise HTTPException(status_code=403, detail="ip not allowed")
    from prometheus_client import generate_latest

    scrape_metric.labels(outcome="success").inc()
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type="text/plain; version=0.0.4")


def create_app(
    *,
    allocator: AtomicAllocator,
    settings: APISettings,
    auth_config: AuthConfig,
    redis_client=None,
) -> FastAPI:
    logger = build_logger()
    redis_client = redis_client or create_redis_client(settings.redis_url)
    namespaces = RedisNamespaces(settings.redis_namespace)
    retry_config = RedisRetryConfig(
        attempts=max(1, settings.redis_max_retries),
        base_delay=max(0.001, settings.redis_base_delay_ms / 1000),
        max_delay=max(settings.redis_base_delay_ms / 1000, settings.redis_max_delay_ms / 1000),
        jitter=max(0.0, settings.redis_jitter_ms / 1000),
    )
    redis_executor = RedisExecutor(config=retry_config, namespace=settings.redis_namespace)
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
        logger=logger,
        namespaces=namespaces,
        redis_client=redis_client,
        counter_runtime=counter_runtime,
        counter_metrics=counter_metrics,
        year_provider=year_provider,
    )
    jwt_deny = JWTDenyList(redis=redis_client, namespaces=namespaces, executor=redis_executor)
    auth_config.jwt_deny_list = jwt_deny
    app = FastAPI(title="Student Allocation API", version="4.0", default_response_class=JSONResponse)
    rate_limiter = RedisSlidingWindowLimiter(
        redis=redis_client,
        namespaces=namespaces,
        fail_open=settings.rate_limit_fail_open,
        executor=redis_executor,
    )
    idempotency_repo = RedisIdempotencyRepository(
        redis=redis_client,
        namespaces=namespaces,
        ttl_seconds=settings.idempotency_ttl_seconds,
        executor=redis_executor,
    )
    rate_limit_state = MiddlewareState(
        logger=logger,
        auth_config=auth_config,
        rate_limit_config=RateLimitConfig(
            default_rule=RateLimitRule(settings.rate_limit_default, settings.rate_limit_window),
            per_route={
                "/allocations": RateLimitRule(settings.rate_limit_allocations, settings.rate_limit_window),
                "/status": RateLimitRule(settings.rate_limit_status, settings.rate_limit_window),
                "/counter/allocate": RateLimitRule(
                    settings.rate_limit_allocations,
                    settings.rate_limit_window,
                ),
                "/counter/preview": RateLimitRule(
                    settings.rate_limit_status,
                    settings.rate_limit_window,
                ),
            },
            fail_open=settings.rate_limit_fail_open,
        ),
        metrics_token=settings.metrics_token,
        metrics_ip_allowlist=set(settings.metrics_ip_allowlist),
        max_body_bytes=settings.max_body_bytes,
        namespaces=namespaces,
        rate_limiter=rate_limiter,
        idempotency_repository=idempotency_repo,
    )
    setup_middlewares(app, state=rate_limit_state, allowed_origins=settings.allowed_origins)

    router = APIRouter()

    @router.post("/allocations", response_model=AllocationResponseDTO)
    async def create_allocation(
        request: Request,
        response: Response,
        payload: AllocationRequestDTO,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AllocationResponseDTO:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        consumer_id = getattr(request.state, "consumer_id", "anonymous")
        with InFlightTracker(path="/allocations", method="POST"):
            span = start_trace(
                TraceContext(
                    correlation_id=correlation_id,
                    consumer_id=consumer_id,
                    path="/allocations",
                    method="POST",
                )
            )
            try:
                get_metric("alloc_attempt_total").labels(outcome="attempt").inc()
                result = await asyncio.get_event_loop().run_in_executor(None, _wrap_service, payload, allocator)
                enriched = result.model_copy()
                enriched.correlation_id = correlation_id
                remaining = getattr(request.state, "rate_limit_remaining", "0")
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    await reservation.commit(enriched.model_dump(by_alias=True))
                    get_metric("idempotency_events_total").labels(
                        op="POST",
                        endpoint="/allocations",
                        outcome="committed",
                        reason="completed",
                    ).inc()
                get_metric("alloc_attempt_total").labels(outcome="success").inc()
                return enriched
            except HTTPException:
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    await reservation.abort()
                raise
            except Exception as exc:  # pragma: no cover - safety net
                get_metric("alloc_attempt_total").labels(outcome="error").inc()
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    await reservation.abort()
                raise _http_error("INTERNAL", correlation_id, details=str(exc))
            finally:
                enrich_span(span, status_code=200)

    @router.post("/counter/allocate")
    async def counter_allocate(request: Request, response: Response) -> dict[str, object]:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        with InFlightTracker(path="/counter/allocate", method="POST"):
            span = start_trace(
                TraceContext(
                    correlation_id=correlation_id,
                    consumer_id=getattr(request.state, "consumer_id", "anonymous"),
                    path="/counter/allocate",
                    method="POST",
                )
            )
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
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    await reservation.commit(envelope)
                    get_metric("idempotency_events_total").labels(
                        op="POST",
                        endpoint="/counter/allocate",
                        outcome="committed",
                        reason="completed",
                    ).inc()
                remaining = getattr(request.state, "rate_limit_remaining", "0")
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-Correlation-ID"] = correlation_id
                return envelope
            except CounterRuntimeError as exc:
                reservation = getattr(request.state, "idempotency_reservation", None)
                if reservation:
                    await reservation.abort()
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
                enrich_span(span, status_code=response.status_code)

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
        with InFlightTracker(path="/counter/preview", method="GET"):
            span = start_trace(
                TraceContext(
                    correlation_id=correlation_id,
                    consumer_id=getattr(request.state, "consumer_id", "anonymous"),
                    path="/counter/preview",
                    method="GET",
                )
            )
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
                enrich_span(span, status_code=response.status_code)

    @router.get("/status", response_model=StatusResponseDTO)
    async def status(request: Request, response: Response) -> StatusResponseDTO:
        request.state._start_time = time.perf_counter()
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        with InFlightTracker(path="/status", method="GET"):
            span = start_trace(
                TraceContext(
                    correlation_id=correlation_id,
                    consumer_id=getattr(request.state, "consumer_id", "anonymous"),
                    path="/status",
                    method="GET",
                )
            )
            try:
                return StatusResponseDTO()
            finally:
                enrich_span(span, status_code=200)

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
        if exc.status_code == 401:
            code = "AUTH_REQUIRED"
            message = "احراز هویت لازم است"
        else:
            code = "INTERNAL"
            message = "خطای داخلی سامانه"
        return _error_response(status_code=exc.status_code, code=code, message=message, correlation_id=correlation_id)

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next: Callable[[Request], Any]):
        request.state._start_time = time.perf_counter()
        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("Content-Type")
            if content_type != "application/json; charset=utf-8":
                correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
                response = _error_response(
                    status_code=ERROR_MAP["CONTENT_TYPE_INVALID"][0],
                    code="CONTENT_TYPE_INVALID",
                    message=ERROR_MAP["CONTENT_TYPE_INVALID"][2],
                    correlation_id=correlation_id,
                )
                await finalize_response(
                    request,
                    response,
                    logger=logger,
                    status_code=response.status_code,
                    error_code="CONTENT_TYPE_INVALID",
                    outcome="validation_error",
                )
                record_metrics(
                    path=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    latency_s=0.0,
                )
                return response
            body = await request.body()
            request._body = body
            max_body = app.state.middleware_state.max_body_bytes
            if len(body) > max_body:
                correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
                response = _error_response(
                    status_code=ERROR_MAP["BODY_TOO_LARGE"][0],
                    code="BODY_TOO_LARGE",
                    message=ERROR_MAP["BODY_TOO_LARGE"][2],
                    correlation_id=correlation_id,
                )
                await finalize_response(
                    request,
                    response,
                    logger=logger,
                    status_code=response.status_code,
                    error_code="BODY_TOO_LARGE",
                    outcome="validation_error",
                )
                record_metrics(
                    path=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    latency_s=0.0,
                )
                return response
        try:
            response: Response = await call_next(request)
        except PermissionError as exc:
            correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
            msg = str(exc)
            code = msg.split("|")[0] if "|" in msg else "AUTH_REQUIRED"
            message = msg.split("|")[1] if "|" in msg else "احراز هویت لازم است"
            error = _error_response(
                status_code=ERROR_MAP.get(code, (401, code, message))[0],
                code=code,
                message=message,
                correlation_id=correlation_id,
            )
            await finalize_response(request, error, logger=logger, status_code=error.status_code, error_code=code, outcome="auth_failure")
            record_metrics(path=request.url.path, method=request.method, status_code=error.status_code, latency_s=0.0)
            remaining = getattr(request.state, "rate_limit_remaining", None)
            if remaining is not None:
                error.headers["X-RateLimit-Remaining"] = str(remaining)
            return error
        except RedisOperationError as exc:
            correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
            response = _error_response(
                status_code=ERROR_MAP["INTERNAL"][0],
                code="INTERNAL",
                message=ERROR_MAP["INTERNAL"][2],
                correlation_id=correlation_id,
                details=str(exc),
            )
            await finalize_response(
                request,
                response,
                logger=logger,
                status_code=response.status_code,
                error_code="INTERNAL",
                outcome="internal_error",
            )
            record_metrics(path=request.url.path, method=request.method, status_code=response.status_code, latency_s=0.0)
            return response
        except ValueError as exc:
            correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
            msg = str(exc)
            if "|" in msg:
                code, message = msg.split("|", 1)
            else:
                code, message = "VALIDATION_ERROR", "اطلاعات ارسال‌شده نامعتبر است"
            status_code, _, persian = ERROR_MAP.get(code, (422, code, message))
            response = _error_response(status_code=status_code, code=code, message=persian, correlation_id=correlation_id)
            if code == "RATE_LIMIT_EXCEEDED":
                retry_after = getattr(request.state, "retry_after", 1)
                response.headers["Retry-After"] = str(int(retry_after))
            remaining = getattr(request.state, "rate_limit_remaining", None)
            if remaining is not None:
                response.headers["X-RateLimit-Remaining"] = str(remaining)
            await finalize_response(request, response, logger=logger, status_code=status_code, error_code=code, outcome="validation_error")
            record_metrics(path=request.url.path, method=request.method, status_code=status_code, latency_s=0.0)
            return response
        else:
            latency = time.perf_counter() - request.state._start_time
            record_metrics(path=request.url.path, method=request.method, status_code=response.status_code, latency_s=latency)
            remaining = getattr(request.state, "rate_limit_remaining", None)
            if remaining is not None and "X-RateLimit-Remaining" not in response.headers:
                response.headers["X-RateLimit-Remaining"] = str(remaining)
            await finalize_response(request, response, logger=logger, status_code=response.status_code, outcome="success")
            return response

    async def metrics_handler(request: Request) -> Response:
        return await _metrics_endpoint(request, api_state, rate_limit_state)

    app.add_api_route(
        "/metrics",
        metrics_handler,
        methods=["GET"],
        include_in_schema=False,
    )

    app.state.api_state = api_state
    app.state.middleware_state = rate_limit_state

    return app


def get_debug_context(app: FastAPI) -> dict[str, Any]:
    api_state: APIState = getattr(app.state, "api_state")
    middleware_state: MiddlewareState = getattr(app.state, "middleware_state")
    return {
        "redis_namespace": api_state.namespaces.base,
        "rate_limit_state": get_rate_limit_info(),
        "middlewares": [mw.cls.__name__ for mw in app.user_middleware],
        "metrics_token_configured": bool(middleware_state.metrics_token),
        "timestamp": time.time(),
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
