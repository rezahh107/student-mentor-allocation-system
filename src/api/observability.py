"""Observability utilities for the hardened allocation API."""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Any, Callable, Iterable, Iterator

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
)

try:  # pragma: no cover - optional dependency wiring
    from opentelemetry import trace
except Exception:  # pragma: no cover - graceful fallback
    trace = None

try:  # pragma: no cover - optional JSON acceleration
    import orjson
except Exception:  # pragma: no cover - optional dependency missing
    orjson = None

from .patterns import zero_width_pattern

ZERO_WIDTH_RE = zero_width_pattern()
NON_DIGIT_RE = re.compile(r"\D")


correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
consumer_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("consumer_id", default="anonymous")


@dataclass(slots=True)
class ObservabilityConfig:
    """Configuration for observability primitives."""

    service_name: str = "allocation-api"
    pii_salt: str = "allocation-api"
    registry: CollectorRegistry | None = None
    log_level: int = logging.INFO
    success_log_sample_rate: int = 1
    latency_budget_ms: float = 200.0


class PersianJSONFormatter(logging.Formatter):
    """Structured JSON formatter with deterministic Persian payloads."""

    def __init__(self) -> None:
        super().__init__()
        self._dumps = self._resolve_dumps()

    @staticmethod
    def _resolve_dumps() -> Callable[[dict[str, Any]], str]:
        if orjson is not None:  # pragma: no branch - simple selection

            def _dumps(payload: dict[str, Any]) -> str:
                return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS).decode("utf-8")

            return _dumps

        def _fallback(payload: dict[str, Any]) -> str:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        return _fallback

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - inherited docstring irrelevant
        entries: list[tuple[str, Any]] = []
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            entries.extend(structured.items())
        existing = {key for key, _ in entries}
        if "msg" not in existing:
            entries.append(("msg", record.getMessage()))
        if "level" not in existing:
            entries.append(("level", record.levelname.lower()))
        if "ts" not in existing:
            entries.append(("ts", datetime.now(timezone.utc).isoformat()))
        payload = {key: value for key, value in entries}
        return self._dumps(payload)


@dataclass(slots=True)
class Observability:
    """Aggregates logging, metrics and tracing helpers."""

    config: ObservabilityConfig
    registry: CollectorRegistry = field(init=False)
    logger: logging.Logger = field(init=False)
    http_requests_total: Counter = field(init=False)
    http_request_duration_seconds: Histogram = field(init=False)
    http_requests_in_flight: Gauge = field(init=False)
    auth_fail_total: Counter = field(init=False)
    rate_limit_reject_total: Counter = field(init=False)
    alloc_attempt_total: Counter = field(init=False)
    latency_budget_exceeded_total: Counter = field(init=False)
    idempotency_cache_total: Counter = field(init=False)
    idempotency_lock_total: Counter = field(init=False)
    idempotency_lock_contention_total: Counter = field(init=False)
    idempotency_degraded_total: Counter = field(init=False)
    redis_retry_total: Counter = field(init=False)
    idempotency_cache_compressed_total: Counter = field(init=False)
    idempotency_cache_uncompressed_total: Counter = field(init=False)
    idempotency_cache_bytes_total: Counter = field(init=False)
    idempotency_cache_serialize_seconds: Histogram = field(init=False)
    idempotency_cache_replay_seconds: Histogram = field(init=False)
    idempotency_cache_buffer_bytes: Gauge = field(init=False)
    _tracer: Any = field(init=False, repr=False, default=None)
    _success_counter: Iterator[int] = field(init=False, repr=False)
    _request_counter_cache: dict[tuple[str, str, str], Any] = field(init=False, repr=False, default_factory=dict)
    _request_hist_cache: dict[tuple[str, str], Any] = field(init=False, repr=False, default_factory=dict)
    _latency_budget_cache: dict[tuple[str, str], Any] = field(init=False, repr=False, default_factory=dict)
    _auth_fail_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _rate_limit_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _alloc_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_lock_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_lock_contention_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_degraded_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _redis_retry_cache: dict[tuple[str, str], Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_bytes_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_serialize_hist_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _idempotency_replay_hist_cache: dict[str, Any] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.registry = self.config.registry or REGISTRY
        self.logger = logging.getLogger(self.config.service_name)
        self._configure_logger()
        self.http_requests_total = Counter(
            "http_requests_total",
            "Count of HTTP requests.",
            labelnames=("path", "method", "status"),
            registry=self.registry,
        )
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "Request latency distribution.",
            labelnames=("path", "method"),
            registry=self.registry,
        )
        self.http_requests_in_flight = Gauge(
            "http_requests_in_flight",
            "Number of in-flight requests.",
            registry=self.registry,
        )
        self.auth_fail_total = Counter(
            "auth_fail_total",
            "Authentication failures by reason.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.rate_limit_reject_total = Counter(
            "rate_limit_reject_total",
            "Rejected requests due to rate limiting.",
            labelnames=("route",),
            registry=self.registry,
        )
        self.alloc_attempt_total = Counter(
            "alloc_attempt_total",
            "Allocation attempts grouped by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.latency_budget_exceeded_total = Counter(
            "http_latency_budget_exceeded_total",
            "Requests exceeding configured latency budget.",
            labelnames=("path", "method"),
            registry=self.registry,
        )
        self.idempotency_cache_total = Counter(
            "idempotency_cache_total",
            "Counts of idempotency cache events by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.idempotency_lock_total = Counter(
            "idempotency_lock_total",
            "Counts of idempotency lock acquisitions by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.idempotency_lock_contention_total = Counter(
            "idempotency_lock_contention_total",
            "Counts of idempotency lock contention events.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.idempotency_degraded_total = Counter(
            "idempotency_degraded_total",
            "Counts of degraded mode activations for idempotency.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.redis_retry_total = Counter(
            "redis_retry_total",
            "Redis retry attempts grouped by operation and reason.",
            labelnames=("operation", "reason"),
            registry=self.registry,
        )
        self.idempotency_cache_compressed_total = Counter(
            "idemp_cache_compressed_total",
            "Counts of compressed idempotency cache writes.",
            registry=self.registry,
        )
        self.idempotency_cache_uncompressed_total = Counter(
            "idemp_cache_uncompressed_total",
            "Counts of uncompressed idempotency cache writes.",
            registry=self.registry,
        )
        self.idempotency_cache_bytes_total = Counter(
            "idemp_cache_bytes_total",
            "Total bytes processed by idempotency cache operations.",
            labelnames=("event",),
            registry=self.registry,
        )
        self.idempotency_cache_serialize_seconds = Histogram(
            "idemp_cache_serialize_seconds",
            "Serialization latency for idempotency cache writes.",
            labelnames=("mode",),
            registry=self.registry,
        )
        self.idempotency_cache_replay_seconds = Histogram(
            "idemp_cache_replay_seconds",
            "Replay latency for idempotency cache hits.",
            labelnames=("mode",),
            registry=self.registry,
        )
        self.idempotency_cache_buffer_bytes = Gauge(
            "idemp_cache_buffer_bytes",
            "Current in-memory buffer size while serializing idempotent responses.",
            registry=self.registry,
        )
        if trace is not None:  # pragma: no cover - optional instrumentation
            self._tracer = trace.get_tracer(self.config.service_name)
        else:  # pragma: no cover - fallback
            self._tracer = None
        self._success_counter = count(start=0, step=1)

    # Logging helpers -------------------------------------------------
    def _configure_logger(self) -> None:
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(PersianJSONFormatter())
            self.logger.addHandler(handler)
        self.logger.setLevel(self.config.log_level)
        self.logger.propagate = False

    def _base_payload(self) -> list[tuple[str, Any]]:
        return [
            ("correlation_id", get_correlation_id()),
            ("request_id", get_request_id()),
            ("consumer_id", get_consumer_id()),
        ]

    def emit(self, *, level: int, msg: str, **fields: Any) -> None:
        entries = self._base_payload()
        sanitized = self._sanitize(fields)
        entries.extend(sanitized.items())
        entries.append(("msg", msg))
        payload = {key: value for key, value in entries}
        self.logger.log(level, msg, extra={"structured": payload})

    def log_request(
        self,
        *,
        path: str,
        method: str,
        status: int,
        latency_ms: float,
        outcome: str,
        error_code: str | None = None,
    ) -> None:
        if outcome == "SUCCESS" and self.config.success_log_sample_rate > 1:
            current = next(self._success_counter)
            if current % self.config.success_log_sample_rate != 0:
                return
        payload = {
            "path": path,
            "method": method,
            "status": status,
            "latency_ms": round(latency_ms, 3),
            "outcome": outcome,
        }
        if error_code:
            payload["error_code"] = error_code
        self.emit(level=logging.INFO, msg="درخواست پردازش شد", **payload)

    # Metrics helpers -------------------------------------------------
    def record_request_metrics(self, *, path: str, method: str, status: int, latency_seconds: float) -> None:
        status_key = (path, method, str(status))
        counter = self._request_counter_cache.get(status_key)
        if counter is None:
            counter = self.http_requests_total.labels(path=path, method=method, status=str(status))
            self._request_counter_cache[status_key] = counter
        counter.inc()

        hist_key = (path, method)
        histogram = self._request_hist_cache.get(hist_key)
        if histogram is None:
            histogram = self.http_request_duration_seconds.labels(path=path, method=method)
            self._request_hist_cache[hist_key] = histogram
        histogram.observe(latency_seconds)

        if latency_seconds * 1000 > self.config.latency_budget_ms:
            budget_metric = self._latency_budget_cache.get(hist_key)
            if budget_metric is None:
                budget_metric = self.latency_budget_exceeded_total.labels(path=path, method=method)
                self._latency_budget_cache[hist_key] = budget_metric
            budget_metric.inc()

    def increment_auth_failure(self, reason: str) -> None:
        metric = self._auth_fail_cache.get(reason)
        if metric is None:
            metric = self.auth_fail_total.labels(reason=reason)
            self._auth_fail_cache[reason] = metric
        metric.inc()

    def increment_rate_limit(self, route: str) -> None:
        metric = self._rate_limit_cache.get(route)
        if metric is None:
            metric = self.rate_limit_reject_total.labels(route=route)
            self._rate_limit_cache[route] = metric
        metric.inc()

    def increment_allocation_attempt(self, outcome: str) -> None:
        metric = self._alloc_cache.get(outcome)
        if metric is None:
            metric = self.alloc_attempt_total.labels(outcome=outcome)
            self._alloc_cache[outcome] = metric
        metric.inc()

    def increment_idempotency(self, outcome: str) -> None:
        metric = self._idempotency_cache.get(outcome)
        if metric is None:
            metric = self.idempotency_cache_total.labels(outcome=outcome)
            self._idempotency_cache[outcome] = metric
        metric.inc()


    def increment_idempotency_lock(self, outcome: str) -> None:
        metric = self._idempotency_lock_cache.get(outcome)
        if metric is None:
            metric = self.idempotency_lock_total.labels(outcome=outcome)
            self._idempotency_lock_cache[outcome] = metric
        metric.inc()

    def increment_idempotency_lock_contention(self, reason: str) -> None:
        metric = self._idempotency_lock_contention_cache.get(reason)
        if metric is None:
            metric = self.idempotency_lock_contention_total.labels(reason=reason)
            self._idempotency_lock_contention_cache[reason] = metric
        metric.inc()

    def increment_idempotency_degraded(self, reason: str) -> None:
        metric = self._idempotency_degraded_cache.get(reason)
        if metric is None:
            metric = self.idempotency_degraded_total.labels(reason=reason)
            self._idempotency_degraded_cache[reason] = metric
        metric.inc()

    def increment_redis_retry(self, operation: str, reason: str) -> None:
        key = (operation, reason)
        metric = self._redis_retry_cache.get(key)
        if metric is None:
            metric = self.redis_retry_total.labels(operation=operation, reason=reason)
            self._redis_retry_cache[key] = metric
        metric.inc()

    def observe_idempotency_serialization(
        self,
        *,
        raw_bytes: int,
        stored_bytes: int,
        compressed: bool,
        duration_seconds: float,
    ) -> None:
        mode = "compressed" if compressed else "plain"
        hist = self._idempotency_serialize_hist_cache.get(mode)
        if hist is None:
            hist = self.idempotency_cache_serialize_seconds.labels(mode=mode)
            self._idempotency_serialize_hist_cache[mode] = hist
        hist.observe(duration_seconds)

        raw_metric = self._idempotency_bytes_cache.get("store_raw")
        if raw_metric is None:
            raw_metric = self.idempotency_cache_bytes_total.labels(event="store_raw")
            self._idempotency_bytes_cache["store_raw"] = raw_metric
        raw_metric.inc(raw_bytes)

        stored_metric = self._idempotency_bytes_cache.get("store_persisted")
        if stored_metric is None:
            stored_metric = self.idempotency_cache_bytes_total.labels(event="store_persisted")
            self._idempotency_bytes_cache["store_persisted"] = stored_metric
        stored_metric.inc(stored_bytes)

        if compressed:
            self.idempotency_cache_compressed_total.inc()
        else:
            self.idempotency_cache_uncompressed_total.inc()

    def observe_idempotency_replay(
        self,
        *,
        payload_bytes: int,
        compressed: bool,
        duration_seconds: float,
    ) -> None:
        mode = "compressed" if compressed else "plain"
        hist = self._idempotency_replay_hist_cache.get(mode)
        if hist is None:
            hist = self.idempotency_cache_replay_seconds.labels(mode=mode)
            self._idempotency_replay_hist_cache[mode] = hist
        hist.observe(duration_seconds)

        replay_metric = self._idempotency_bytes_cache.get("replay_bytes")
        if replay_metric is None:
            replay_metric = self.idempotency_cache_bytes_total.labels(event="replay")
            self._idempotency_bytes_cache["replay_bytes"] = replay_metric
        replay_metric.inc(payload_bytes)

    def track_idempotency_buffer(self, size: int) -> None:
        self.idempotency_cache_buffer_bytes.set(max(size, 0))

    # Tracing helpers -------------------------------------------------
    def start_span(self, name: str):  # pragma: no cover - instrumentation stub
        if self._tracer is None:
            return _NullContext()
        return self._tracer.start_as_current_span(name)

    # PII sanitisation ------------------------------------------------
    def _sanitize(self, fields: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                sanitized[key] = None
                continue
            if key in {"national_id", "student_id", "nid"}:
                sanitized[key] = self.hash_identifier(str(value))
                continue
            if key in {"phone", "mobile"}:
                sanitized[key] = mask_phone(str(value))
                continue
            sanitized[key] = value
        return sanitized

    def hash_identifier(self, value: str) -> str:
        normalized = ZERO_WIDTH_RE.sub("", value)
        digest = hashlib.sha256()
        digest.update((self.config.pii_salt + normalized).encode("utf-8"))
        return digest.hexdigest()


def set_correlation_id(value: str) -> None:
    correlation_id_ctx.set(value)


def get_correlation_id() -> str:
    return correlation_id_ctx.get()


def set_request_id(value: str) -> None:
    request_id_ctx.set(value)


def get_request_id() -> str:
    return request_id_ctx.get()


def set_consumer_id(value: str) -> None:
    consumer_id_ctx.set(value or "anonymous")


def get_consumer_id() -> str:
    return consumer_id_ctx.get()


def mask_phone(value: str) -> str:
    digits = NON_DIGIT_RE.sub("", ZERO_WIDTH_RE.sub("", value))
    if len(digits) < 4:
        return "***"
    prefix = digits[:2]
    suffix = digits[-2:]
    masked = "*" * max(len(digits) - 4, 0)
    return f"{prefix}{masked}{suffix}"


class _NullContext:
    """Fallback context manager used when tracing is disabled."""

    def __enter__(self) -> None:  # pragma: no cover - trivial
        return None

    def __exit__(self, *exc: object) -> None:  # pragma: no cover - trivial
        return None


def iter_registry_metrics(registry: CollectorRegistry) -> Iterable[str]:
    """Expose registry metrics for tests/documentation."""

    for metric in registry.collect():
        for sample in metric.samples:
            yield f"{sample.name}{sample.labels} {sample.value}"
