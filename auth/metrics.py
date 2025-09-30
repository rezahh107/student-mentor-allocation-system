from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram


@dataclass(slots=True)
class AuthMetrics:
    registry: CollectorRegistry
    ok_total: Counter
    fail_total: Counter
    duration_seconds: Histogram
    retry_attempts_total: Counter
    retry_exhaustion_total: Counter
    retry_backoff_seconds: Histogram

    @classmethod
    def build(cls, registry: CollectorRegistry | None = None) -> "AuthMetrics":
        registry = registry or CollectorRegistry()
        ok_total = Counter(
            "auth_ok_total",
            "Successful SSO authentications",
            labelnames=("provider",),
            registry=registry,
        )
        fail_total = Counter(
            "auth_fail_total",
            "Failed SSO authentications",
            labelnames=("provider", "reason"),
            registry=registry,
        )
        duration_seconds = Histogram(
            "auth_duration_seconds",
            "Authentication latency per provider",
            labelnames=("provider",),
            registry=registry,
        )
        retry_attempts_total = Counter(
            "auth_retry_attempts_total",
            "Retries performed against identity providers",
            labelnames=("adapter", "reason"),
            registry=registry,
        )
        retry_exhaustion_total = Counter(
            "auth_retry_exhaustion_total",
            "Authentication retries exhausted",
            labelnames=("adapter", "reason"),
            registry=registry,
        )
        retry_backoff_seconds = Histogram(
            "auth_retry_backoff_seconds",
            "Backoff duration applied between retry attempts",
            labelnames=("adapter", "reason"),
            registry=registry,
        )
        return cls(
            registry=registry,
            ok_total=ok_total,
            fail_total=fail_total,
            duration_seconds=duration_seconds,
            retry_attempts_total=retry_attempts_total,
            retry_exhaustion_total=retry_exhaustion_total,
            retry_backoff_seconds=retry_backoff_seconds,
        )


__all__ = ["AuthMetrics"]
