from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from phase6_import_to_sabt.middleware.metrics import MiddlewareMetrics

REQUEST_LATENCY = "request_latency_seconds"


@dataclass(slots=True)
class ServiceMetrics:
    registry: CollectorRegistry
    request_latency: Histogram
    request_total: Counter
    readiness_total: Counter
    middleware: MiddlewareMetrics
    exporter_duration_seconds: Histogram
    exporter_bytes_total: Counter
    auth_ok_total: Counter
    auth_fail_total: Counter
    download_signed_total: Counter
    token_rotation_total: Counter
    retry_attempts_total: Counter
    retry_exhausted_total: Counter
    retry_backoff_seconds: Histogram
    ratelimit_tokens: Gauge
    ratelimit_drops_total: Counter

    def reset(self) -> None:
        if hasattr(self.registry, "_names_to_collectors"):
            self.registry._names_to_collectors.clear()  # type: ignore[attr-defined]
        if hasattr(self.registry, "_collector_to_names"):
            self.registry._collector_to_names.clear()  # type: ignore[attr-defined]


def _build_histogram(namespace: str, name: str, documentation: str, *, registry: CollectorRegistry, buckets: Iterable[float]) -> Histogram:
    return Histogram(
        f"{namespace}_{name}",
        documentation,
        registry=registry,
        buckets=tuple(buckets),
    )


def build_metrics(namespace: str, registry: CollectorRegistry | None = None) -> ServiceMetrics:
    reg = registry or CollectorRegistry()
    request_latency = _build_histogram(
        namespace,
        REQUEST_LATENCY,
        "HTTP request latency seconds",
        registry=reg,
        buckets=(0.05, 0.1, 0.2, 0.5, 1.0),
    )
    request_total = Counter(
        f"{namespace}_request_total",
        "Total processed requests",
        registry=reg,
        labelnames=("method", "path", "status"),
    )
    readiness_total = Counter(
        f"{namespace}_readiness_checks",
        "Readiness check results",
        registry=reg,
        labelnames=("component", "status"),
    )
    rate_limit_tokens = Gauge(
        f"{namespace}_ratelimit_tokens",
        "Rate limit tokens remaining per route",
        registry=reg,
        labelnames=("route",),
    )
    rate_limit_drops_total = Counter(
        f"{namespace}_ratelimit_drops_total",
        "Rate limit drops grouped by route",
        registry=reg,
        labelnames=("route",),
    )
    middleware_metrics = MiddlewareMetrics(
        rate_limit_decision_total=Counter(
            f"{namespace}_rate_limit_decision_total",
            "Rate limit decisions",
            registry=reg,
            labelnames=("decision",),
        ),
        idempotency_hits_total=Counter(
            f"{namespace}_idempotency_hits_total",
            "Idempotency hit/miss decisions",
            registry=reg,
            labelnames=("outcome",),
        ),
        idempotency_replays_total=Counter(
            f"{namespace}_idempotency_replays_total",
            "Idempotent replay responses",
            registry=reg,
        ),
        rate_limit_latency_seconds=_build_histogram(
            namespace,
            "rate_limit_latency_seconds",
            "Rate limit middleware latency",
            registry=reg,
            buckets=(0.001, 0.01, 0.05, 0.1),
        ),
        idempotency_latency_seconds=_build_histogram(
            namespace,
            "idempotency_latency_seconds",
            "Idempotency middleware latency",
            registry=reg,
            buckets=(0.001, 0.01, 0.05, 0.1),
        ),
        auth_latency_seconds=_build_histogram(
            namespace,
            "auth_latency_seconds",
            "Auth middleware latency",
            registry=reg,
            buckets=(0.001, 0.01, 0.05, 0.1),
        ),
        rate_limit_tokens=rate_limit_tokens,
        rate_limit_drops_total=rate_limit_drops_total,
    )
    exporter_duration = _build_histogram(
        namespace,
        "exporter_duration_seconds",
        "CSV exporter write duration",
        registry=reg,
        buckets=(0.01, 0.05, 0.1, 0.2, 0.5),
    )
    exporter_bytes = Counter(
        f"{namespace}_exporter_bytes_total",
        "Total bytes written by exporter",
        registry=reg,
    )
    auth_ok_total = Counter(
        f"{namespace}_auth_ok_total",
        "Authentication success count",
        registry=reg,
        labelnames=("role",),
    )
    auth_fail_total = Counter(
        f"{namespace}_auth_fail_total",
        "Authentication failures",
        registry=reg,
        labelnames=("reason",),
    )
    download_signed_total = Counter(
        f"{namespace}_download_signed_total",
        "Download signing events",
        registry=reg,
        labelnames=("outcome",),
    )
    token_rotation_total = Counter(
        f"{namespace}_token_rotation_total",
        "Token rotation actions",
        registry=reg,
        labelnames=("event",),
    )
    retry_attempts_total = Counter(
        f"{namespace}_retry_attempts_total",
        "HTTP client retry attempts",
        registry=reg,
        labelnames=("operation", "route"),
    )
    retry_exhausted_total = Counter(
        f"{namespace}_retry_exhausted_total",
        "HTTP client retry exhaustion count",
        registry=reg,
        labelnames=("operation", "route"),
    )
    retry_backoff_seconds = Histogram(
        f"{namespace}_retry_backoff_seconds",
        "Deterministic retry backoff schedule seconds",
        registry=reg,
        labelnames=("operation", "route"),
        buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0),
    )
    return ServiceMetrics(
        registry=reg,
        request_latency=request_latency,
        request_total=request_total,
        readiness_total=readiness_total,
        middleware=middleware_metrics,
        exporter_duration_seconds=exporter_duration,
        exporter_bytes_total=exporter_bytes,
        auth_ok_total=auth_ok_total,
        auth_fail_total=auth_fail_total,
        download_signed_total=download_signed_total,
        token_rotation_total=token_rotation_total,
        retry_attempts_total=retry_attempts_total,
        retry_exhausted_total=retry_exhausted_total,
        retry_backoff_seconds=retry_backoff_seconds,
        ratelimit_tokens=rate_limit_tokens,
        ratelimit_drops_total=rate_limit_drops_total,
    )


def render_metrics(metrics: ServiceMetrics) -> bytes:
    return generate_latest(metrics.registry)


__all__ = ["REQUEST_LATENCY", "ServiceMetrics", "build_metrics", "render_metrics"]
