"""FastAPI application entrypoint for the hardened allocation API."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.admin_ui import AdminConfig, build_admin_router
from src.api.idempotency_store import (
    IdempotencyConflictError,
    IdempotencyRecord,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
)
from src.api.middleware import (
    APIKeyProvider,
    AuthenticationConfig,
    AuthenticationMiddleware,
    BodySizeLimitMiddleware,
    ContentTypeValidationMiddleware,
    CorrelationIdMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    RateLimiter,
    SecurityHeadersMiddleware,
    StaticCredential,
    build_error_response,
    install_cors,
)
from src.api.observability import Observability, ObservabilityConfig, get_correlation_id
from src.api.patterns import ascii_token_pattern, zero_width_pattern
from src.api.rate_limit_backends import (
    InMemoryRateLimitBackend,
    RateLimitBackend,
    RedisRateLimitBackend,
)
from src.api.security_hardening import constant_time_compare, ensure_metrics_authorized
from src.api.models import validate_national_code
from src.core.normalize import normalize_digits
from src.infrastructure.persistence.models import APIKeyModel
from src.phase3_allocation import AllocationRequest, AllocationResult, AtomicAllocator

ASCII_TOKEN = ascii_token_pattern()
ASCII_TOKEN_EXTENDED = ascii_token_pattern(512)
ZERO_WIDTH_RE = zero_width_pattern()
DEFAULT_ALLOWED_ORIGINS = ("https://studentalloc.example.com",)
APP_START_TS = time.time()

try:  # pragma: no cover - optional performance extras
    import uvloop  # type: ignore
except Exception:  # pragma: no cover - optional dependency missing
    uvloop = None

try:  # pragma: no cover - optional HTTP parser
    import httptools  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover - optional dependency missing
    httptools = None

_RUNTIME_HINTS: dict[str, str] | None = None


def _ensure_runtime_extras() -> dict[str, str]:
    """Enable uvloop/httptools when installed and expose hints."""

    global _RUNTIME_HINTS
    if _RUNTIME_HINTS is not None:
        return _RUNTIME_HINTS

    hints: dict[str, str] = {}
    if uvloop is not None:  # pragma: no cover - depends on optional extra
        try:
            policy = asyncio.get_event_loop_policy()
            if not isinstance(policy, uvloop.EventLoopPolicy):  # type: ignore[attr-defined]
                uvloop.install()  # type: ignore[union-attr]
            hints["loop"] = "uvloop"
        except Exception:  # pragma: no cover - fallback to default asyncio
            hints["loop"] = "asyncio"
    else:
        hints["loop"] = "asyncio"

    if httptools is not None:  # pragma: no cover - optional extra
        os.environ.setdefault("UVICORN_HTTP", "httptools")
        hints["http"] = "httptools"
    else:
        hints["http"] = "h11"

    _RUNTIME_HINTS = hints
    return hints


@dataclass(slots=True)
class HardenedAPIConfig:
    """Runtime configuration for the hardened API."""

    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    max_body_bytes: int = 32 * 1024
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 30
    idempotency_ttl_seconds: int = 24 * 3600
    pii_salt: str = "allocation-api"
    static_tokens: dict[str, StaticCredential] = field(default_factory=dict)
    jwt_secret: str | None = None
    leeway_seconds: int = 120
    metrics_token: str | None = None
    metrics_ip_allowlist: set[str] = field(default_factory=lambda: {"127.0.0.1"})
    redis_url: str | None = None
    admin_token: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    success_log_sample_rate: int = 1
    latency_budget_ms: float = 200.0
    excel_max_bytes: int = 10 * 1024 * 1024
    required_scopes: dict[str, set[str]] = field(default_factory=lambda: {
        "/allocations": {"alloc:write"},
        "/status": {"alloc:read"},
    })

    @classmethod
    def from_env(cls) -> "HardenedAPIConfig":
        allowed_origins = tuple(filter(None, os.getenv("ALLOC_API_ALLOWED_ORIGINS", "").split(","))) or DEFAULT_ALLOWED_ORIGINS
        max_body = int(os.getenv("ALLOC_API_MAX_BODY", "32768"))
        rate_limit = int(os.getenv("ALLOC_API_RATE_PER_MIN", "60"))
        rate_burst = int(os.getenv("ALLOC_API_RATE_BURST", str(rate_limit)))
        pii_salt = os.getenv("ALLOC_API_PII_SALT", "allocation-api")
        metrics_token = os.getenv("ALLOC_API_METRICS_TOKEN")
        metrics_ips = {ip.strip() for ip in os.getenv("ALLOC_API_METRICS_IPS", "127.0.0.1").split(",") if ip.strip()}
        jwt_secret = os.getenv("ALLOC_API_JWT_SECRET")
        leeway = int(os.getenv("ALLOC_API_JWT_LEEWAY", "120"))
        redis_url = os.getenv("REDIS_URL")
        admin_token = os.getenv("ALLOC_API_ADMIN_TOKEN")
        jwt_issuer = os.getenv("ALLOC_API_JWT_ISS")
        jwt_audience = os.getenv("ALLOC_API_JWT_AUD")
        success_log_sample_rate = max(1, int(os.getenv("ALLOC_API_LOG_SAMPLE_RATE", "1")))
        latency_budget_ms = float(os.getenv("ALLOC_API_LATENCY_BUDGET_MS", "200"))
        excel_max_bytes = int(os.getenv("ALLOC_API_EXCEL_MAX_BYTES", str(10 * 1024 * 1024)))
        static_tokens = _parse_static_tokens(os.getenv("ALLOC_API_STATIC_TOKENS", ""))
        required_scopes = {
            path.strip(): {scope for scope in scopes.split(" ") if scope}
            for raw in filter(None, os.getenv("ALLOC_API_REQUIRED_SCOPES", "").split(";"))
            for path, scopes in [raw.split("=", 1)]
        }
        if not required_scopes:
            required_scopes = {
                "/allocations": {"alloc:write"},
                "/status": {"alloc:read"},
            }
        return cls(
            allowed_origins=allowed_origins,
            max_body_bytes=max_body,
            rate_limit_per_minute=rate_limit,
            rate_limit_burst=rate_burst,
            idempotency_ttl_seconds=int(os.getenv("ALLOC_API_IDEMPOTENCY_TTL", str(24 * 3600))),
            pii_salt=pii_salt,
            static_tokens=static_tokens,
            jwt_secret=jwt_secret,
            leeway_seconds=leeway,
            metrics_token=metrics_token,
            metrics_ip_allowlist=metrics_ips or {"127.0.0.1"},
            redis_url=redis_url,
            admin_token=admin_token,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            success_log_sample_rate=success_log_sample_rate,
            latency_budget_ms=latency_budget_ms,
            excel_max_bytes=excel_max_bytes,
            required_scopes=required_scopes,
        )


def _parse_static_tokens(raw: str) -> dict[str, StaticCredential]:
    credentials: dict[str, StaticCredential] = {}
    if not raw:
        return credentials
    for item in filter(None, raw.split(";")):
        token, _, scope_text = item.partition(":")
        token = token.strip()
        if not token or not ASCII_TOKEN_EXTENDED.fullmatch(token):
            continue
        scopes = frozenset(filter(None, scope_text.split()))
        consumer_id = f"token:{hash(token) & 0xFFFF:x}"
        credentials[token] = StaticCredential(token=token, scopes=scopes, consumer_id=consumer_id)
    return credentials


class AllocationRequestBody(BaseModel):
    """Incoming payload for allocation requests."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    student_id: str = Field(validation_alias=AliasChoices("student_id", "studentId", "studentNationalId"))
    mentor_id: int = Field(validation_alias=AliasChoices("mentor_id", "mentorId"))
    reg_center: int = Field(validation_alias=AliasChoices("reg_center", "regCenter"))
    reg_status: int = Field(validation_alias=AliasChoices("reg_status", "regStatus"))
    gender: int = Field(validation_alias=AliasChoices("gender"))
    request_id: str | None = Field(default=None, validation_alias=AliasChoices("request_id", "requestId"))
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    year_code: str | None = Field(default=None, validation_alias=AliasChoices("year_code", "yearCode"))

    @field_validator("student_id", mode="before")
    @classmethod
    def _validate_student(cls, value: Any) -> str:
        if isinstance(value, str) and ZERO_WIDTH_RE.search(value):
            raise ValueError("شناسهٔ دانش‌آموز حاوی نویسهٔ نامرئی است")
        text = _canonical_string(value)
        if not text or not text.isdigit():
            raise ValueError("شناسهٔ دانش‌آموز نامعتبر است")
        if not validate_national_code(text):
            raise ValueError("شناسهٔ دانش‌آموز نامعتبر است")
        return text

    @field_validator("mentor_id", "reg_center", "reg_status", "gender", mode="before")
    @classmethod
    def _validate_integers(cls, value: Any, info: Any) -> int:
        field_name = info.field_name
        allowed_map = {
            "reg_center": {0, 1, 2},
            "reg_status": {0, 1, 3},
            "gender": {0, 1},
        }
        number = _parse_int(value, field_name)
        allowed = allowed_map.get(field_name)
        if allowed and number not in allowed:
            raise ValueError(f"مقدار فیلد {field_name} مجاز نیست")
        return number

    @field_validator("payload", "metadata", mode="before")
    @classmethod
    def _ensure_mapping(cls, value: Any) -> dict[str, Any]:
        if value in (None, "", {}):
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(ZERO_WIDTH_RE.sub("", value))
            except json.JSONDecodeError as exc:
                raise ValueError("ساختار JSON نامعتبر است") from exc
            if not isinstance(parsed, dict):
                raise ValueError("ساختار JSON باید دیکشنری باشد")
            return parsed
        raise ValueError("ساختار JSON باید دیکشنری باشد")

    @field_validator("year_code", mode="before")
    @classmethod
    def _normalize_year(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = _canonical_string(value)
        if not text:
            return None
        if not text.isdigit() or len(text) not in (2, 4):
            raise ValueError("کد سال نامعتبر است")
        return text

    @field_validator("request_id", mode="before")
    @classmethod
    def _sanitize_request_id(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = _canonical_string(value)
        return text or None


class AllocationResponseBody(BaseModel):
    """Response envelope mapping allocation results."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    allocation_id: int | None = Field(serialization_alias="allocationId", default=None)
    allocation_code: str | None = Field(serialization_alias="allocationCode", default=None)
    year_code: str | None = Field(serialization_alias="yearCode", default=None)
    mentor_id: int | None = Field(serialization_alias="mentorId", default=None)
    status: str
    message: str
    error_code: str | None = Field(serialization_alias="errorCode", default=None)
    idempotency_key: str = Field(serialization_alias="idempotencyKey")
    outbox_event_id: str | None = Field(serialization_alias="outboxEventId", default=None)
    dry_run: bool = Field(serialization_alias="dryRun", default=False)
    correlation_id: str = Field(serialization_alias="correlationId")


class StatusResponse(BaseModel):
    """Health/status endpoint response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(serialization_alias="status")
    correlation_id: str = Field(serialization_alias="correlationId")
    uptime_seconds: float = Field(serialization_alias="uptimeSeconds")
    service_time: str = Field(serialization_alias="serviceTime")


@dataclass(slots=True)
class _APIKeyInfo:
    consumer_id: str
    scopes: set[str]
    name: str | None
    expires_at: datetime | None
    is_active: bool


class DatabaseAPIKeyProvider:
    """Loads API keys from the relational database."""

    def __init__(self, session_factory: Callable[[], Session], *, salt: str) -> None:
        self._session_factory = session_factory
        self._salt = salt

    async def verify(self, value: str) -> _APIKeyInfo | None:
        return await asyncio.to_thread(self._verify_sync, value)

    def _verify_sync(self, value: str) -> _APIKeyInfo | None:
        prefix = value[:16]
        with self._session_factory() as session:
            record = session.execute(
                select(APIKeyModel).where(APIKeyModel.key_prefix == prefix)
            ).scalar_one_or_none()
            if record is None:
                return None
            if not record.is_active:
                return None
            if record.expires_at and record.expires_at <= datetime.now(timezone.utc):
                return None
            digest = _hash_identifier(record.salt + value)
            if not constant_time_compare(digest, record.key_hash):
                return None
            record.last_used_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()
            scopes = {scope for scope in (record.scopes or "").split(",") if scope}
            consumer_id = _hash_identifier(self._salt + record.key_hash)
            return _APIKeyInfo(
                consumer_id=consumer_id,
                scopes=scopes,
                name=record.name,
                expires_at=record.expires_at,
                is_active=record.is_active,
            )


def create_app(
    allocator: AtomicAllocator,
    *,
    config: HardenedAPIConfig | None = None,
    registry: CollectorRegistry | None = None,
    session_factory: Callable[[], Session] | None = None,
    api_key_provider: APIKeyProvider | None = None,
) -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = config or HardenedAPIConfig.from_env()
    runtime_hints = _ensure_runtime_extras()
    obs = Observability(
        ObservabilityConfig(
            service_name="student-allocation-api",
            pii_salt=settings.pii_salt,
            registry=registry,
            success_log_sample_rate=settings.success_log_sample_rate,
            latency_budget_ms=settings.latency_budget_ms,
        )
    )
    if settings.redis_url:
        rate_backend: RateLimitBackend = RedisRateLimitBackend(settings.redis_url, namespace="alloc")
        idempotency_store: IdempotencyStore = RedisIdempotencyStore(settings.redis_url, namespace="alloc")
    else:
        rate_backend = InMemoryRateLimitBackend()
        idempotency_store = InMemoryIdempotencyStore()

    app = FastAPI(title="Student Allocation API", version="5.0")
    app.state.runtime_extras = runtime_hints
    app.state.started_at = APP_START_TS
    app.state.observability = obs
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(ContentTypeValidationMiddleware, methods=("POST",), paths=("/allocations",))
    app.add_middleware(
        BodySizeLimitMiddleware,
        limit_bytes=settings.max_body_bytes,
        methods=("POST",),
        paths=("/allocations",),
    )

    auth_config = AuthenticationConfig(
        static_credentials=settings.static_tokens,
        jwt_secret=settings.jwt_secret,
        leeway_seconds=settings.leeway_seconds,
        jwt_issuer=settings.jwt_issuer,
        jwt_audience=settings.jwt_audience,
        required_scopes=settings.required_scopes,
        public_paths={"/metrics", "/admin"},
    )
    provider = api_key_provider
    if provider is None and session_factory is not None:
        provider = DatabaseAPIKeyProvider(session_factory, salt=settings.pii_salt)

    app.add_middleware(AuthenticationMiddleware, config=auth_config, observability=obs, api_key_provider=provider)

    rate_limiter = RateLimiter(
        backend=rate_backend,
        capacity=settings.rate_limit_burst,
        refill_rate_per_sec=max(settings.rate_limit_per_minute, 1) / 60.0,
    )
    app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, observability=obs)
    app.add_middleware(SecurityHeadersMiddleware, allow_origins=settings.allowed_origins)
    app.add_middleware(ObservabilityMiddleware, observability=obs)
    install_cors(app, allow_origins=settings.allowed_origins)

    if settings.admin_token and session_factory is not None:
        admin_router = build_admin_router(
            config=AdminConfig(admin_token=settings.admin_token),
            session_factory=session_factory,
            observability=obs,
        )
        app.include_router(admin_router)

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return build_error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part not in {"body", "__root__"}),
                "message": error.get("msg"),
            }
            for error in exc.errors()
        ]
        return build_error_response(
            HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message_fa": "اعتبارسنجی ورودی نامعتبر است",
                    "details": errors,
                },
            )
        )

    @app.post("/allocations", response_model=AllocationResponseBody, responses=_error_responses())
    async def create_allocation(request: Request, payload: AllocationRequestBody) -> JSONResponse:
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            idempotency_key = _canonical_string(idempotency_key)
            if not ASCII_TOKEN.fullmatch(idempotency_key):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "VALIDATION_ERROR", "message_fa": "قالب Idempotency-Key نامعتبر است"},
                )
        body_hash = _hash_payload(payload.model_dump(mode="json"))
        cached_entry: IdempotencyRecord | None = None
        if idempotency_key:
            try:
                cached_entry = await idempotency_store.get(
                    idempotency_key,
                    body_hash=body_hash,
                    ttl_seconds=settings.idempotency_ttl_seconds,
                )
            except IdempotencyConflictError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "CONFLICT", "message_fa": "کلید ایدمپوتنسی با بدنهٔ متفاوت تکرار شده است"},
                ) from exc
            if cached_entry:
                obs.increment_idempotency("hit")
                headers = {**cached_entry.headers, "X-Idempotent-Replay": "true"}
                headers.setdefault("X-Correlation-ID", get_correlation_id())
                return JSONResponse(status_code=cached_entry.status_code, content=cached_entry.response, headers=headers)
            else:
                obs.increment_idempotency("miss")

        try:
            alloc_request = AllocationRequest(
                studentId=payload.student_id,
                mentorId=payload.mentor_id,
                requestId=payload.request_id,
                payload=payload.payload,
                metadata={
                    **payload.metadata,
                    "reg_center": payload.reg_center,
                    "reg_status": payload.reg_status,
                    "gender": payload.gender,
                },
                yearCode=payload.year_code,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message_fa": "اعتبارسنجی ورودی نامعتبر است",
                    "details": exc.errors(),
                },
            ) from exc
        try:
            result: AllocationResult = allocator.allocate(alloc_request, dry_run=False)
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - defensive branch
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "INTERNAL", "message_fa": "خطای داخلی در سرویس تخصیص"},
            ) from exc

        obs.increment_allocation_attempt(result.status)
        response_body = AllocationResponseBody(
            allocation_id=result.allocation_id,
            allocation_code=result.allocation_code,
            year_code=result.year_code,
            mentor_id=result.mentor_id,
            status=result.status,
            message=result.message,
            error_code=result.error_code,
            idempotency_key=result.idempotency_key,
            outbox_event_id=result.outbox_event_id,
            dry_run=result.dry_run,
            correlation_id=get_correlation_id(),
        ).model_dump(by_alias=True)
        status_code = status.HTTP_200_OK if result.status in {"OK", "ALREADY_ASSIGNED", "CONFIRMED", "DRY_RUN"} else status.HTTP_409_CONFLICT
        headers = {"X-Correlation-ID": get_correlation_id()}
        if idempotency_key:
            await idempotency_store.set(
                idempotency_key,
                IdempotencyRecord(
                    body_hash=body_hash,
                    response=response_body,
                    status_code=status_code,
                    stored_at=time.time(),
                    headers=headers,
                ),
                ttl_seconds=settings.idempotency_ttl_seconds,
            )
            obs.increment_idempotency("stored")
        return JSONResponse(status_code=status_code, content=response_body, headers=headers)

    @app.get("/status", response_model=StatusResponse, responses=_error_responses())
    async def service_status() -> StatusResponse:
        correlation_id = get_correlation_id() or str(uuid4())
        uptime = time.time() - APP_START_TS
        return StatusResponse(
            status="ok",
            correlation_id=correlation_id,
            uptime_seconds=round(uptime, 3),
            service_time=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        ensure_metrics_authorized(
            request,
            token=settings.metrics_token,
            ip_allowlist=settings.metrics_ip_allowlist,
        )
        output = generate_latest(obs.registry)
        return Response(content=output, media_type=CONTENT_TYPE_LATEST)

    return app


def _hash_payload(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_identifier(serialized)


def _hash_identifier(value: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(value.encode("utf-8"))
    return digest.hexdigest()
def _canonical_string(value: Any) -> str:
    if value is None:
        return ""
    text = normalize_digits(str(value))
    text = ZERO_WIDTH_RE.sub("", text)
    return text.strip()


def _parse_int(value: Any, field_name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = _canonical_string(value)
    if not text or not text.isdigit():
        raise ValueError(f"مقدار فیلد {field_name} باید عددی باشد")
    return int(text)


def _error_responses() -> dict[int | str, dict[str, Any]]:
    return {
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    }


class ErrorEnvelope(BaseModel):
    """Standardised error schema."""

    model_config = ConfigDict(extra="forbid")

    error: dict[str, Any]
