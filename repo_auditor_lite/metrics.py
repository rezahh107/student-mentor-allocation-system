from __future__ import annotations

import os

PROMETHEUS_MISSING_ERROR = (
    "کتابخانهٔ prometheus_client در دسترس نیست؛ لطفاً آن را نصب کرده یا "
    "متغیر AUDITOR_METRICS_BACKEND=noop را تنظیم کنید."
)

_BACKEND_SETTING = os.getenv("AUDITOR_METRICS_BACKEND", "auto").strip().lower()
if _BACKEND_SETTING not in {"auto", "prom", "noop"}:
    _BACKEND_SETTING = "auto"

if _BACKEND_SETTING == "noop":
    from .metrics_noop import CollectorRegistry, Counter, Gauge
elif _BACKEND_SETTING == "prom":
    try:  # pragma: no cover - executed when prometheus_client is available
        from prometheus_client import CollectorRegistry, Counter, Gauge
    except ModuleNotFoundError as exc:  # pragma: no cover - fail with Persian guidance
        raise RuntimeError(PROMETHEUS_MISSING_ERROR) from exc
else:
    try:  # pragma: no cover - executed when prometheus_client is available
        from prometheus_client import CollectorRegistry, Counter, Gauge
    except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
        from .metrics_noop import CollectorRegistry, Counter, Gauge

_REGISTRY = CollectorRegistry()
METRICS_BACKEND = "noop" if CollectorRegistry.__module__.endswith("metrics_noop") else "prom"


def _create_counters(registry: CollectorRegistry) -> dict[str, Counter]:
    return {
        "audits_total": Counter(
            "repo_auditor_audits_total",
            "Count of audit operations by file and status.",
            ("file", "status"),
            registry=registry,
        ),
        "fixes_total": Counter(
            "repo_auditor_fixes_total",
            "Count of file rewrites by file and outcome.",
            ("file", "outcome"),
            registry=registry,
        ),
        "retry_total": Counter(
            "repo_auditor_retry_total",
            "Count of retry attempts per operation.",
            ("operation",),
            registry=registry,
        ),
    }


_COUNTERS = _create_counters(_REGISTRY)


def get_registry() -> CollectorRegistry:
    return _REGISTRY


def reset_registry() -> CollectorRegistry:
    global _REGISTRY, _COUNTERS
    _REGISTRY = CollectorRegistry()
    _COUNTERS = _create_counters(_REGISTRY)
    return _REGISTRY


def counters() -> dict[str, Counter]:
    return _COUNTERS


def inc_audit(file_name: str, status: str) -> None:
    counters()["audits_total"].labels(file=file_name, status=status).inc()


def inc_fix(file_name: str, outcome: str) -> None:
    counters()["fixes_total"].labels(file=file_name, outcome=outcome).inc()


def inc_retry(operation: str) -> None:
    counters()["retry_total"].labels(operation=operation).inc()


__all__ = [
    "METRICS_BACKEND",
    "counters",
    "get_registry",
    "reset_registry",
    "inc_audit",
    "inc_fix",
    "inc_retry",
]
