from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Histogram


@dataclass(slots=True)
class MiddlewareMetrics:
    """Prometheus helpers for middleware instrumentation."""

    rate_limit_decision_total: Counter
    idempotency_hits_total: Counter
    idempotency_replays_total: Counter
    rate_limit_latency_seconds: Histogram
    idempotency_latency_seconds: Histogram
    auth_latency_seconds: Histogram

    def observe_rate_limit(self, decision: str, duration: float) -> None:
        self.rate_limit_decision_total.labels(decision=decision).inc()
        self.rate_limit_latency_seconds.observe(duration)

    def observe_idempotency(self, outcome: str, duration: float) -> None:
        self.idempotency_hits_total.labels(outcome=outcome).inc()
        self.idempotency_latency_seconds.observe(duration)

    def observe_idempotency_replay(self) -> None:
        self.idempotency_replays_total.inc()

    def observe_auth(self, duration: float) -> None:
        self.auth_latency_seconds.observe(duration)


__all__ = ["MiddlewareMetrics"]
