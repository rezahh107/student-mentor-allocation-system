from __future__ import annotations

"""Prometheus registry helpers used across tests."""

from contextlib import contextmanager
from typing import Iterator

from prometheus_client import CollectorRegistry, Counter, Histogram

_REGISTRY: CollectorRegistry | None = None
_RETRY_COUNTER: Counter | None = None
_RETRY_HISTOGRAM: Histogram | None = None
_RETRY_EXHAUSTIONS: Counter | None = None
_EXPORT_DURATION: Histogram | None = None
_EXPORT_BYTES: Counter | None = None


def get_registry() -> CollectorRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CollectorRegistry()
    return _REGISTRY


def reset_registry() -> None:
    global _REGISTRY, _RETRY_COUNTER, _RETRY_HISTOGRAM, _RETRY_EXHAUSTIONS, _EXPORT_DURATION, _EXPORT_BYTES
    _REGISTRY = None
    _RETRY_COUNTER = None
    _RETRY_HISTOGRAM = None
    _RETRY_EXHAUSTIONS = None
    _EXPORT_DURATION = None
    _EXPORT_BYTES = None


def get_retry_counter() -> Counter:
    global _RETRY_COUNTER
    if _RETRY_COUNTER is None:
        _RETRY_COUNTER = Counter(
            "retries_total",
            "Total retries per operation",
            labelnames=("operation", "result"),
            registry=get_registry(),
        )
    return _RETRY_COUNTER


def get_retry_histogram() -> Histogram:
    global _RETRY_HISTOGRAM
    if _RETRY_HISTOGRAM is None:
        _RETRY_HISTOGRAM = Histogram(
            "retry_delay_seconds",
            "Retry delays per operation",
            labelnames=("operation",),
            registry=get_registry(),
            buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5),
        )
    return _RETRY_HISTOGRAM


def get_retry_exhaustion_counter() -> Counter:
    global _RETRY_EXHAUSTIONS
    if _RETRY_EXHAUSTIONS is None:
        _RETRY_EXHAUSTIONS = Counter(
            "retry_exhaustions_total",
            "Total exhausted retries per operation",
            labelnames=("operation",),
            registry=get_registry(),
        )
    return _RETRY_EXHAUSTIONS


def get_export_duration_histogram() -> Histogram:
    global _EXPORT_DURATION
    if _EXPORT_DURATION is None:
        _EXPORT_DURATION = Histogram(
            "export_duration_seconds",
            "Duration of export phases",
            labelnames=("phase",),
            registry=get_registry(),
            buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2),
        )
    return _EXPORT_DURATION


def get_export_bytes_counter() -> Counter:
    global _EXPORT_BYTES
    if _EXPORT_BYTES is None:
        _EXPORT_BYTES = Counter(
            "export_file_bytes_total",
            "Total bytes written by exporter",
            labelnames=("format",),
            registry=get_registry(),
        )
    return _EXPORT_BYTES


@contextmanager
def registry_scope() -> Iterator[CollectorRegistry]:
    try:
        reset_registry()
        yield get_registry()
    finally:
        reset_registry()
