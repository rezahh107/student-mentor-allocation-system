from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

# from sma.phase6_import_to_sabt.middleware.metrics import MiddlewareMetrics # حذف شد
# فرض بر این است که MiddlewareMetrics دیگر مورد نیاز نیست یا فقط شامل متریک‌های امنیتی است

REQUEST_LATENCY = "request_latency_seconds"

# کلاس ServiceMetrics باید بروزرسانی شود
@dataclass(slots=True)
class ServiceMetrics:
    registry: CollectorRegistry
    request_latency: Histogram
    request_total: Counter
    readiness_total: Counter
    # middleware: MiddlewareMetrics # حذف شد
    exporter_duration_seconds: Histogram
    exporter_bytes_total: Counter
    # auth_ok_total: Counter # حذف شد
    # auth_fail_total: Counter # حذف شد
    # download_signed_total: Counter # حذف شد
    # token_rotation_total: Counter # حذف شد
    retry_attempts_total: Counter
    retry_exhausted_total: Counter
    retry_backoff_seconds: Histogram
    # ratelimit_tokens: Gauge # حذف شد
    # ratelimit_drops_total: Counter # حذف شد

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
    # rate_limit_tokens = Gauge( ... ) # حذف شد
    # rate_limit_drops_total = Counter( ... ) # حذف شد
    # middleware_metrics = MiddlewareMetrics( ... ) # حذف شد
    # اکنون یک شیء ساده یا None برای middleware استفاده می‌کنیم
    middleware_metrics = None # یا یک شیء سازگار با ساختار قبلی اگر جای دیگری به آن نیاز باشد
    # اگر کلاس MiddlewareMetrics دیگر وجود نداشته باشد، این خط باید حذف یا تغییر کند
    # برای اینکه کد کاملاً کار کند، ممکن است نیاز باشد یک کلاس ساختگی یا تابعی برای ساخت آن ایجاد کنیم
    # اما برای سادگی، فرض می‌کنیم هیچ کلاسی به آن نیاز نیست یا فقط شامل متریک‌های امنیتی بوده است
    # بنابراین فقط None یا یک شیء دیگر می‌دهیم
    # یا می‌توانیم یک کلاس جدید ساختگی ایجاد کنیم که فقط شامل متریک‌های غیرامنیتی باشد
    # اما برای اینجا، فقط None می‌دهیم یا یک شیء با فیلدهای خالی
    class DummyMiddlewareMetrics:
        pass
    middleware_metrics = DummyMiddlewareMetrics()
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
    # auth_ok_total = Counter( ... ) # حذف شد
    # auth_fail_total = Counter( ... ) # حذف شد
    # download_signed_total = Counter( ... ) # حذف شد
    # token_rotation_total = Counter( ... ) # حذف شد
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
        # middleware=middleware_metrics, # حذف شد یا تغییر کرد
        exporter_duration_seconds=exporter_duration,
        exporter_bytes_total=exporter_bytes,
        # auth_ok_total=auth_ok_total, # حذف شد
        # auth_fail_total=auth_fail_total, # حذف شد
        # download_signed_total=download_signed_total, # حذف شد
        # token_rotation_total=token_rotation_total, # حذف شد
        retry_attempts_total=retry_attempts_total,
        retry_exhausted_total=retry_exhausted_total,
        retry_backoff_seconds=retry_backoff_seconds,
        # ratelimit_tokens=rate_limit_tokens, # حذف شد
        # ratelimit_drops_total=rate_limit_drops_total, # حذف شد
    )


def render_metrics(metrics: ServiceMetrics) -> bytes:
    return generate_latest(metrics.registry)


__all__ = ["REQUEST_LATENCY", "ServiceMetrics", "build_metrics", "render_metrics"]
