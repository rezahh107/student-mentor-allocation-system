from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from prometheus_client import Counter, CollectorRegistry, generate_latest

AUDIT_NAMESPACE = "automation_audit"


@dataclass
class Metrics:
    registry: CollectorRegistry
    audit_runs: Counter
    audit_failures: Counter
    retry_attempts: Counter
    retry_exhausted: Counter


def build_metrics(registry: Optional[CollectorRegistry] = None) -> Metrics:
    registry = registry or CollectorRegistry()
    audit_runs = Counter(
        "runs_total",
        "Total automation audit executions",
        namespace=AUDIT_NAMESPACE,
        registry=registry,
    )
    audit_failures = Counter(
        "failures_total",
        "Automation audit failures",
        namespace=AUDIT_NAMESPACE,
        registry=registry,
    )
    retry_attempts = Counter(
        "retry_attempts_total",
        "Retry attempts performed",
        namespace=AUDIT_NAMESPACE,
        registry=registry,
    )
    retry_exhausted = Counter(
        "retry_exhausted_total",
        "Retries exhausted",
        namespace=AUDIT_NAMESPACE,
        registry=registry,
    )
    return Metrics(registry, audit_runs, audit_failures, retry_attempts, retry_exhausted)


def render_metrics(metrics: Metrics) -> bytes:
    return generate_latest(metrics.registry)
