"""Observability helpers for ImportToSabt services."""

from __future__ import annotations

import inspect
import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Coroutine, Optional, get_type_hints

from prometheus_client import CollectorRegistry, Counter, Histogram


LOGGER = logging.getLogger(__name__)


class MetricsCollector:
    """Shared Prometheus metrics wrapper for critical ImportToSabt flows."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._signature_failures = Counter(
            "download_signature_failures_total",
            "Signature verification failures by reason.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self._signature_validations = Counter(
            "download_signature_validations_total",
            "Download signature validations split by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self._export_manifest_requests = Counter(
            "export_manifest_requests_total",
            "Export manifest retrieval attempts by status.",
            labelnames=("status",),
            registry=self.registry,
        )
        self._readiness_gate_trips = Counter(
            "readiness_gate_trips_total",
            "Number of readiness gate evaluations by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self._signature_blocks = Counter(
            "download_signature_blocks_total",
            "Temporary IP blocks triggered by signature abuse.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self._honeypot_hits = Counter(
            "download_honeypot_hits_total",
            "Honeypot endpoint hits by source.",
            labelnames=("source",),
            registry=self.registry,
        )
        self._endpoint_latency = Histogram(
            "download_endpoint_latency_ms",
            "Endpoint latency distribution in milliseconds.",
            labelnames=("endpoint",),
            registry=self.registry,
            buckets=(10, 25, 50, 75, 100, 200, 350, 500, 1000, float("inf")),
        )
        self._span_latency = Histogram(
            "download_span_latency_ms",
            "Internal span latency distribution in milliseconds.",
            labelnames=("span",),
            registry=self.registry,
            buckets=(5, 10, 20, 40, 80, 160, 320, float("inf")),
        )
        self._retry_attempts = Counter(
            "download_retry_attempts_total",
            "Retry attempts grouped by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )

    def record_signature_failure(self, *, reason: str) -> None:
        self._signature_failures.labels(reason=reason).inc()
        self._signature_validations.labels(outcome="failure").inc()

    def record_signature_success(self) -> None:
        self._signature_validations.labels(outcome="success").inc()

    def record_signature_block(self, *, reason: str) -> None:
        self._signature_blocks.labels(reason=reason).inc()

    def record_manifest_request(self, *, status: str) -> None:
        self._export_manifest_requests.labels(status=status).inc()

    def record_readiness_trip(self, *, outcome: str) -> None:
        self._readiness_gate_trips.labels(outcome=outcome).inc()

    def record_honeypot_hit(self, *, source: str) -> None:
        self._honeypot_hits.labels(source=source).inc()

    def observe_endpoint_latency(self, *, endpoint: str, duration_ms: float) -> None:
        self._endpoint_latency.labels(endpoint=endpoint).observe(duration_ms)

    def observe_span_latency(self, *, span: str, duration_ms: float) -> None:
        self._span_latency.labels(span=span).observe(duration_ms)

    def record_retry_attempt(self, *, outcome: str) -> None:
        self._retry_attempts.labels(outcome=outcome).inc()

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable snapshot of counter values for assertions."""

        def _counter_samples(counter: Counter) -> dict[str, float]:
            return {tuple(sorted(sample.labels.items())): sample.value for sample in counter.collect()[0].samples}

        return {
            "signature_failures": _counter_samples(self._signature_failures),
            "signature_validations": _counter_samples(self._signature_validations),
            "export_manifest_requests": _counter_samples(self._export_manifest_requests),
            "readiness_gate_trips": _counter_samples(self._readiness_gate_trips),
            "signature_blocks": _counter_samples(self._signature_blocks),
            "honeypot_hits": _counter_samples(self._honeypot_hits),
            "retry_attempts": _counter_samples(self._retry_attempts),
        }


@contextmanager
def trace_span(name: str, *, collector: MetricsCollector | None = None) -> Callable[[], None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        if collector is not None:
            collector.observe_span_latency(span=name, duration_ms=duration_ms)


def _resolve_request_from_bound(bound: inspect.BoundArguments | None) -> Any:
    if not bound:
        return None
    for value in bound.arguments.values():
        if value is None:
            continue
        if hasattr(value, "app") and hasattr(value, "state"):
            return value
    return None


def profile_endpoint(*, threshold_ms: float) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    """Measure endpoint latency and emit structured warnings for slow handlers."""

    def decorator(
        func: Callable[..., Coroutine[Any, Any, Any]]
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        signature = inspect.signature(func)
        try:
            from fastapi import Request as FastAPIRequest  # type: ignore import-error
        except Exception:  # noqa: BLE001 - FastAPI is optional for non-HTTP call sites
            FastAPIRequest = None  # type: ignore[assignment]
        else:
            if "request" in signature.parameters:
                adjusted = []
                for name, parameter in signature.parameters.items():
                    if name == "request":
                        adjusted.append(parameter.replace(annotation=FastAPIRequest))
                    else:
                        adjusted.append(parameter)
                signature = signature.replace(parameters=tuple(adjusted))

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            bound: inspect.BoundArguments | None = None
            exc: Exception | None = None
            try:
                try:
                    bound = signature.bind_partial(*args, **kwargs)
                except Exception:  # noqa: BLE001 - diagnostic path must not fail execution
                    bound = None
                result = await func(*args, **kwargs)
                return result
            except Exception as error:  # noqa: BLE001 - propagate after recording metrics
                exc = error
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                request = _resolve_request_from_bound(bound)
                collector: Optional[MetricsCollector] = None
                if request is not None:
                    app = getattr(request, "app", None)
                    state = getattr(app, "state", None) if app is not None else None
                    collector = getattr(state, "metrics_collector", None)
                if collector is not None:
                    collector.observe_endpoint_latency(endpoint=func.__name__, duration_ms=duration_ms)
                if duration_ms > threshold_ms:
                    LOGGER.warning(
                        "endpoint.slow",
                        extra={
                            "endpoint": func.__name__,
                            "duration_ms": round(duration_ms, 3),
                            "exception": None if exc is None else type(exc).__name__,
                        },
                    )

        wrapper.__signature__ = signature
        try:
            wrapper.__annotations__ = get_type_hints(func)
        except Exception:  # noqa: BLE001 - fallback to shallow copy when hints cannot be resolved
            wrapper.__annotations__ = getattr(func, "__annotations__", {}).copy()
        return wrapper

    return decorator


__all__ = ["MetricsCollector", "profile_endpoint", "trace_span"]
