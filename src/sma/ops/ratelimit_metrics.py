"""Rate limit observability helpers for deterministic tests."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(slots=True)
class RateLimitMetrics:
    namespace: str
    registry: CollectorRegistry
    tokens: Gauge
    drops_total: Counter

    def set_tokens(self, *, route: str, remaining: int) -> None:
        self.tokens.labels(route=route).set(max(0, remaining))

    def record_drop(self, *, route: str) -> None:
        self.drops_total.labels(route=route).inc()


def build_rate_limit_metrics(namespace: str, registry: CollectorRegistry | None = None) -> RateLimitMetrics:
    reg = registry or CollectorRegistry()
    gauge_name = f"{namespace}_ratelimit_tokens"
    counter_name = f"{namespace}_ratelimit_drops_total"
    tokens = _get_or_create_gauge(reg, gauge_name, "Remaining tokens per route.", ("route",))
    drops_total = _get_or_create_counter(reg, counter_name, "Rate limit drops per route.", ("route",))
    return RateLimitMetrics(namespace=namespace, registry=reg, tokens=tokens, drops_total=drops_total)


def _get_or_create_gauge(
    registry: CollectorRegistry, name: str, documentation: str, labelnames: tuple[str, ...]
) -> Gauge:
    existing = getattr(registry, "_names_to_collectors", {}).get(name)
    if isinstance(existing, Gauge):
        return existing
    return Gauge(name, documentation, registry=registry, labelnames=labelnames)


def _get_or_create_counter(
    registry: CollectorRegistry, name: str, documentation: str, labelnames: tuple[str, ...]
) -> Counter:
    existing = getattr(registry, "_names_to_collectors", {}).get(name)
    if isinstance(existing, Counter):
        return existing
    return Counter(name, documentation, registry=registry, labelnames=labelnames)


__all__ = ["RateLimitMetrics", "build_rate_limit_metrics"]
