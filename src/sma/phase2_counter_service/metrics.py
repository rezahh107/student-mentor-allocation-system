# -*- coding: utf-8 -*-
"""Prometheus metrics for the counter service."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, REGISTRY

from .types import GenderLiteral, MeterLike

COUNTER_RESULT_LABELS = ("result",)
COUNTER_CONFLICT_LABELS = ("type",)
COUNTER_FAILURE_LABELS = ("reason",)


class CounterMeters(MeterLike):
    """Wraps Prometheus primitives behind a friendly interface."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._generated = Counter(
            "counter_generated_total",
            "Total generated counters",
            COUNTER_RESULT_LABELS,
            registry=self._registry,
        )
        self._conflicts = Counter(
            "counter_conflict_total",
            "Database conflicts during counter assignment",
            COUNTER_CONFLICT_LABELS,
            registry=self._registry,
        )
        self._failures = Counter(
            "counter_failures_total",
            "Unhandled failures during counter assignment",
            COUNTER_FAILURE_LABELS,
            registry=self._registry,
        )
        self._validation = Counter(
            "counter_validation_errors_total",
            "Validation errors",
            ("code",),
            registry=self._registry,
        )
        self._sequence_exhausted = Counter(
            "counter_sequence_exhausted_total",
            "Sequence exhaustion events per (year,gender)",
            ("year_code", "gender"),
            registry=self._registry,
        )
        self._exporter_health = Gauge(
            "counter_exporter_health",
            "Exporter health gauge (1=healthy)",
            registry=self._registry,
        )
        self._http_started = Gauge(
            "counter_metrics_http_started",
            "Number of active metrics HTTP servers",
            registry=self._registry,
        )

    @property
    def registry(self) -> CollectorRegistry:
        """Return the registry backing the meters."""

        return self._registry

    def record_success(self, gender: GenderLiteral) -> None:
        self._generated.labels(result=f"success_{gender}").inc()

    def record_reuse(self, gender: GenderLiteral) -> None:
        self._generated.labels(result=f"reuse_{gender}").inc()

    def record_validation_error(self, code: str) -> None:
        self._validation.labels(code=code).inc()

    def record_conflict(self, conflict_type: str) -> None:
        self._conflicts.labels(type=conflict_type).inc()

    def record_failure(self, reason: str) -> None:
        self._failures.labels(reason=reason).inc()

    def record_sequence_exhausted(self, year_code: str, gender: GenderLiteral) -> None:
        self._sequence_exhausted.labels(year_code=year_code, gender=str(gender)).inc()

    def exporter_health(self, value: float) -> None:
        self._exporter_health.set(value)

    def http_started(self, value: float) -> None:
        self._http_started.set(value)

    @property
    def exporter_gauge(self) -> Gauge:
        return self._exporter_health

    @property
    def http_gauge(self) -> Gauge:
        return self._http_started


DEFAULT_METERS = CounterMeters()
