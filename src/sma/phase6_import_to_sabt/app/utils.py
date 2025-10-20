from __future__ import annotations

import os
import os
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TYPE_CHECKING

from sma.core.clock import Clock

from sma.phase6_import_to_sabt.app.context import get_current_correlation_id

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from fastapi import FastAPI

ARABIC_DIGITS = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
PERSIAN_DIGITS = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
ZERO_WIDTH = {
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u2060",
}


def normalize_token(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value
    for zw in ZERO_WIDTH:
        cleaned = cleaned.replace(zw, "")
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = cleaned.translate(ARABIC_DIGITS)
    cleaned = cleaned.translate(PERSIAN_DIGITS)
    return cleaned.strip()


def ensure_no_control_chars(items: Iterable[str]) -> None:
    for item in items:
        for ch in item:
            if unicodedata.category(ch)[0] == "C" and ch not in ZERO_WIDTH:
                raise ValueError("Control characters not permitted in headers")


def _callable_or_value(value: Callable[[], Any] | Any | None) -> Any:
    if callable(value):  # type: ignore[call-arg]
        try:
            return value()
        except Exception:  # noqa: BLE001 - diagnostics must be resilient
            return None
    return value


def _memory_snapshot() -> dict[str, int]:
    try:
        import psutil

        process = psutil.Process()
        memory_info = process.memory_info()
        return {
            "rss": memory_info.rss,
            "vms": memory_info.vms,
            "peak_wset": getattr(memory_info, "peak_wset", 0),
        }
    except Exception:  # noqa: BLE001 - psutil optional in CI images
        return {}


def _connection_pool_snapshot(app: "FastAPI" | None) -> dict[str, Any]:
    if app is None:
        return {}
    pool = getattr(app.state, "connection_pool", None)
    if pool is None:
        return {}
    for accessor in ("snapshot", "get_stats", "stats", "info"):
        candidate = getattr(pool, accessor, None)
        if callable(candidate):
            try:
                result = candidate()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(result, Mapping):
                return dict(result)
    numeric_attrs = {name: getattr(pool, name) for name in ("min", "max", "size") if hasattr(pool, name)}
    return {key: int(value) for key, value in numeric_attrs.items() if isinstance(value, int)}


def _cache_metrics_snapshot(app: "FastAPI" | None) -> dict[str, Any]:
    if app is None:
        return {}
    cache_metrics = getattr(app.state, "cache_metrics", None)
    if cache_metrics is None:
        return {}
    snapshot = None
    for accessor in ("snapshot", "dump", "as_dict"):
        method = getattr(cache_metrics, accessor, None)
        if callable(method):
            try:
                snapshot = method()
            except Exception:  # noqa: BLE001
                continue
            break
    if snapshot is None and isinstance(cache_metrics, Mapping):
        snapshot = dict(cache_metrics)
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    return {}


def get_debug_context(
    app: "FastAPI" | None = None,
    *,
    redis_keys: Sequence[str] | Callable[[], Sequence[str]] | None = None,
    namespace: str | None = None,
    last_error: str | None = None,
    middleware_chain: Sequence[str] | Callable[[], Sequence[str]] | None = None,
    rate_limit_state: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a deterministic debug context without leaking secrets."""

    timestamp = Clock.for_tehran().now().isoformat()
    context: dict[str, Any] = {
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": timestamp,
        "correlation_id": get_current_correlation_id(),
        "memory_usage": _memory_snapshot(),
    }
    redis_value = _callable_or_value(redis_keys)
    if isinstance(redis_value, Iterable):
        context["redis_keys"] = [str(item) for item in redis_value]
    if namespace:
        context["namespace"] = namespace
    if last_error is not None:
        context["last_error"] = last_error
    chain_value = _callable_or_value(middleware_chain)
    if isinstance(chain_value, Iterable):
        context["middleware_order"] = [str(item) for item in chain_value]
    rate_limit_value = _callable_or_value(rate_limit_state)
    if isinstance(rate_limit_value, Mapping):
        context["rate_limit_state"] = dict(rate_limit_value)
    if app is not None:
        diagnostics = getattr(app.state, "diagnostics", None)
        if isinstance(diagnostics, Mapping):
            context.setdefault("middleware_order", diagnostics.get("last_chain", []))
            context.setdefault("rate_limit_state", diagnostics.get("last_rate_limit"))
            context["idempotency_state"] = diagnostics.get("last_idempotency")
            context["auth_state"] = diagnostics.get("last_auth")
        context["active_connections"] = _connection_pool_snapshot(app)
        context["cache_hit_rate"] = _cache_metrics_snapshot(app)
    return context


__all__ = ["normalize_token", "ensure_no_control_chars", "get_debug_context"]
