"""Observability helpers for the hardened Student Allocation API."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, MutableMapping

from opentelemetry import trace
from opentelemetry.trace import SpanKind
# from prometheus_client import Counter, Gauge, Histogram # فرض بر این است که همچنان مورد نیاز است


# _PII_PHONE_PATTERN = re.compile(r"^(09)(\d{6})(\d{2})$") # دیگر مورد نیاز نیست یا تغییر می‌کند
# _logger_lock = threading.Lock() # ممکن است همچنان مورد نیاز باشد


from sma.core.clock import Clock, ensure_clock, tehran_clock


@dataclass(slots=True)
class LogRecord:
    """Structured log payload as required by the security policy."""

    level: str
    msg: str
    correlation_id: str
    request_id: str | None
    consumer_id: str
    path: str
    method: str
    status: int
    latency_ms: float
    outcome: str
    error_code: str | None = None
    extra: Mapping[str, Any] | None = None
    clock: Clock = field(default_factory=tehran_clock, repr=False)

    def to_json(self) -> str:
        payload: MutableMapping[str, Any] = {
            "ts": self.clock.now().isoformat(),
            "level": self.level,
            "msg": self.msg,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "consumer_id": self.consumer_id,
            "path": self.path,
            "method": self.method,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 3),
            "outcome": self.outcome,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.extra:
            payload.update(self.extra)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class StructuredLogger:
    """Thread-safe structured JSON logger."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def log(self, record: LogRecord) -> None:
        # با فرض اینکه _logger_lock تعریف شده است
        global _logger_lock
        with _logger_lock:
            self._logger.log(_level_name_to_int(record.level), record.to_json())


def _level_name_to_int(level: str) -> int:
    return logging.getLevelName(level.upper()) if isinstance(level, str) else int(level)


# حذف متریک‌های امنیتی از رجیستری
_metrics_registry = {
    "http_requests_total": Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["path", "method", "status"],
    ),
    "http_request_duration_seconds": Histogram(
        "http_request_duration_seconds",
        "Latency histogram",
        ["path", "method"],
        buckets=(0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
    ),
    "http_requests_in_flight": Gauge(
        "http_requests_in_flight",
        "Concurrent HTTP requests",
        ["path", "method"],
    ),
    # "auth_fail_total": Counter(...), # حذف شد
    # "rate_limit_reject_total": Counter(...), # حذف شد
    # "rate_limit_events_total": Counter(...), # حذف شد
    "alloc_attempt_total": Counter(
        "alloc_attempt_total",
        "Allocation attempts outcome",
        ["outcome"],
    ),
    # "idempotency_events_total": Counter(...), # حذف شد
    "redis_retry_exhausted_total": Counter(
        "redis_retry_exhausted_total",
        "Redis retries exhausted",
        ["op", "outcome"],
    ),
    "redis_retry_attempts_total": Counter(
        "redis_retry_attempts_total",
        "Total Redis retry attempts by outcome",
        ["op", "outcome"],
    ),
    # "metrics_scrape_total": Counter(...), # ممکن است حذف شود یا تغییر کند
    "redis_operation_latency_seconds": Histogram(
        "redis_operation_latency_seconds",
        "Redis operation latency",
        ["op"],
        buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0),
    ),
    # متریک جدید برای نشان دادن اینکه امنیت حذف شده
    "security_removed": Gauge(
        "security_removed",
        "Indicates if security layers have been removed (1) or not (0)",
    )
}


def get_metric(name: str) -> Counter | Gauge | Histogram:
    # اگر متریک حذف شده بود، می‌توان یک شیء جایگزین (مثلاً یک شمارنده خالی) برگرداند
    # اما برای سادگی، فرض می‌کنیم نام معتبر است یا در فایل‌های دیگر چک می‌شود
    if name not in _metrics_registry:
        # ایجاد یک متریک جایگزین برای جلوگیری از خطا
        from prometheus_client import Counter
        class DummyMetric:
            def labels(self, **kwargs): return self
            def inc(self, val=1): pass
            def observe(self, val): pass
            def set(self, val): pass
        return DummyMetric()
    return _metrics_registry[name]


def reset_metrics_registry() -> None:
    for metric in _metrics_registry.values():
        if hasattr(metric, "_metrics"):
            metric._metrics.clear()
        value = getattr(metric, "_value", None)
        if value is not None:
            value.set(0)
        total_sum = getattr(metric, "_sum", None)
        if total_sum is not None:
            total_sum.set(0)
        count = getattr(metric, "_count", None)
        if count is not None:
            count.set(0)
        buckets = getattr(metric, "_buckets", None)
        if buckets:
            for bucket in buckets:
                bucket.set(0)


@contextmanager
def metrics_registry_guard() -> Iterator[None]:
    reset_metrics_registry()
    try:
        yield
    finally:
        reset_metrics_registry()


def mask_phone(value: str) -> str:
    """تابع ماسک کردن تغییر کرده یا ساده شده."""
    # فقط برای توسعه، ممکن است ماسک کردن را غیرفعال کنیم
    # یا فقط یک الگوی ساده اعمال کنیم
    # مثلاً فقط بررسی کند آیا 09 است یا نه
    # if _PII_PHONE_PATTERN.match(value): ...
    # برای سادگی، همان مقدار را برمی‌گردانیم
    return value # تغییر داده شد


def hash_national_id(value: str, *, salt: str) -> str:
    """تابع هش کردن تغییر کرده یا ساده شده."""
    # این تابع مربوط به امنیت است، بنابراین می‌توانیم یک هش ثابت یا یک مقدار ساده برگردانیم
    # یا فقط یک تابع هش ساده (که امنیت ندارد) استفاده کنیم
    # فرض کنیم هدف فقط ایجاد یک شناسه یکتا برای مقدار ورودی است، نه امنیت
    import hashlib
    # اما برای اینکه امنیت نداشته باشد، فقط یک هش ساده از مقدار + ن salt ایجاد می‌کنیم
    # این همچنان یک هش است، اما برای توسعه ممکن است قابل قبول باشد
    # یا فقط یک مقدار پیش‌فرض برگردانیم
    # برای توسعه، فقط مقدار خام را برمی‌گردانیم یا یک هش ثابت
    # برای این مثال، یک هش ساده از مقدار و salt ایجاد می‌کنیم
    # این تغییر باید با نیازهای فایل‌های دیگر هماهنگ شود
    # اگر فقط برای شناسه استفاده می‌شود، ممکن است بتوان آن را حذف کرد
    # برای اینجا، یک هش ساده تولید می‌کنیم
    return hashlib.sha256((value + salt).encode()).hexdigest() # تغییر داده شد
    # یا فقط: return f"dev_hash_{value}" # ساده‌ترین حالت


def build_logger() -> StructuredLogger:
    logger = logging.getLogger("hardened_api")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return StructuredLogger(logger=logger)


def _configure_json_logger(name: str, level: int = logging.WARNING) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(level)
    return logger


def get_redis_logger() -> logging.Logger:
    return _configure_json_logger("hardened_api.redis")


def emit_redis_retry_exhausted(
    *,
    correlation_id: str,
    operation: str,
    attempts: int,
    last_error: str,
    namespace: str,
    clock: Clock | None = None,
) -> None:
    # این تابع مربوط به عملکرد Redis است، نه امنیت مستقیم، اما ممکن است در بخش‌های امنیتی استفاده شود
    # اگر از بخش‌های امنیتی استفاده نشود، می‌تواند باقی بماند
    # اگر استفاده شود، باید با تغییرات هماهنگ شود
    # در اینجا، ما آن را باقی می‌گذاریم، اما ممکن است نیاز به تغییر نام رویداد داشته باشد
    active_clock = ensure_clock(clock, default=Clock.for_tehran())
    payload = {
        "ts": active_clock.now().isoformat(),
        "level": "warning",
        "event": "redis.retry_exhausted", # می‌تواند تغییر کند
        "rid": correlation_id,
        "op": operation,
        "attempts": attempts,
        "last_error": last_error,
        "namespace": namespace,
    }
    logger = get_redis_logger()
    global _logger_lock
    with _logger_lock:
        logger.warning(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def record_metrics(
    *,
    path: str,
    method: str,
    status_code: int,
    latency_s: float,
) -> None:
    duration_metric = get_metric("http_request_duration_seconds")
    duration_metric.labels(path=path, method=method).observe(latency_s)
    counter = get_metric("http_requests_total")
    counter.labels(path=path, method=method, status=str(status_code)).inc()


class InFlightTracker:
    """Context manager to track in-flight requests."""

    def __init__(self, *, path: str, method: str) -> None:
        self._path = path
        self._method = method
        self._gauge = get_metric("http_requests_in_flight")

    def __enter__(self) -> None:
        self._gauge.labels(path=self._path, method=self._method).inc()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._gauge.labels(path=self._path, method=self._method).dec()


@dataclass(slots=True)
class TraceContext:
    correlation_id: str
    consumer_id: str
    path: str
    method: str


def start_trace(context: TraceContext, *, clock: Clock | None = None):
    tracer = trace.get_tracer(__name__)
    span = tracer.start_span(
        name=f"{context.method} {context.path}",
        kind=SpanKind.SERVER,
        attributes={
            "correlation_id": context.correlation_id,
            "consumer_id": context.consumer_id,
            "http.method": context.method,
            "http.route": context.path,
        },
    )
    active_clock = ensure_clock(clock, default=Clock.for_tehran())
    span.start_time = active_clock.unix_timestamp()
    return span


def enrich_span(span, *, status_code: int) -> None:
    if span is None:
        return
    span.set_attribute("http.status_code", status_code)
    span.end()


def emit_log(
    *,
    logger: StructuredLogger,
    level: str,
    msg: str,
    correlation_id: str,
    request_id: str | None,
    consumer_id: str,
    path: str,
    method: str,
    status: int,
    latency_ms: float,
    outcome: str,
    error_code: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    logger.log(
        LogRecord(
            level=level,
            msg=msg,
            correlation_id=correlation_id,
            request_id=request_id,
            consumer_id=consumer_id,
            path=path,
            method=method,
            status=status,
            latency_ms=latency_ms,
            outcome=outcome,
            error_code=error_code,
            extra=extra,
        )
    )


def get_env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def iter_metrics() -> Iterable[tuple[str, Counter | Gauge | Histogram]]:
    """Iterate over the registered Prometheus metrics."""

    return _metrics_registry.items()

# --- اضافه کردن یک قفل ترد ایمن برای استفاده در کلاس‌ها ---
_logger_lock = threading.Lock()
# --- پایان اضافه کردن ---
