"""Dependency readiness probes with deterministic backoff."""

from __future__ import annotations

import hashlib
import socket
import time
from contextlib import suppress
from urllib.parse import urlparse

from prometheus_client import CollectorRegistry, Counter, REGISTRY

from src.phase6_import_to_sabt.sanitization import sanitize_text
from windows_service.errors import DependencyNotReady, ServiceError
from windows_service.normalization import sanitize_env_text

_BACKOFF_MIN_RATIO = 0.8
_BACKOFF_MAX_RATIO = 1.2
_ATTEMPT_CACHE: dict[int, Counter] = {}
_FAILURE_CACHE: dict[int, Counter] = {}


def _counter(
    name: str,
    description: str,
    *,
    labelnames: tuple[str, ...],
    registry: CollectorRegistry,
    cache: dict[int, Counter],
) -> Counter:
    cache_key = id(registry) ^ hash(name)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        collector = Counter(name, description, labelnames=labelnames, registry=registry)
    except ValueError:
        existing = registry._names_to_collectors.get(name)  # type: ignore[attr-defined]
        if isinstance(existing, Counter):
            collector = existing
        else:  # pragma: no cover - defensive
            raise
    cache[cache_key] = collector
    return collector


def _attempt_counter(registry: CollectorRegistry) -> Counter:
    return _counter(
        "readiness_probe_attempts_total",
        "Total readiness probe attempts by dependency.",
        labelnames=("dep", "outcome"),
        registry=registry,
        cache=_ATTEMPT_CACHE,
    )


def _failure_counter(registry: CollectorRegistry) -> Counter:
    return _counter(
        "readiness_probe_failures_total",
        "Total readiness probe failures by reason.",
        labelnames=("dep", "reason"),
        registry=registry,
        cache=_FAILURE_CACHE,
    )


def plan_backoff(seed: str, attempts: int, base_ms: int) -> list[int]:
    if attempts <= 0 or base_ms <= 0:
        return []
    safe_seed = sanitize_text(seed or "winsw") or "winsw"
    sequence: list[int] = []
    for attempt in range(attempts):
        payload = f"{safe_seed}:{attempt}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=4).digest()
        jitter = int.from_bytes(digest, "big") / (2**32 - 1)
        factor = _BACKOFF_MIN_RATIO + (_BACKOFF_MAX_RATIO - _BACKOFF_MIN_RATIO) * jitter
        base_delay = base_ms * (2**attempt)
        sequence.append(max(base_ms, int(base_delay * factor)))
    return sequence


def _probe_postgres(dsn: str, timeout_s: float) -> dict[str, str]:
    parsed = urlparse(dsn)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    start = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout_s):
        pass
    duration_ms = int((time.monotonic() - start) * 1000)
    return {"status": "ok", "host": host, "port": str(port), "duration_ms": str(duration_ms)}


def _probe_redis(url: str, timeout_s: float) -> dict[str, str]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    start = time.monotonic()
    with suppress(ModuleNotFoundError):
        import redis  # type: ignore[import-not-found]

        client = redis.Redis.from_url(url, socket_timeout=timeout_s)
        try:
            client.ping()
        finally:
            with suppress(Exception):
                client.close()
        duration_ms = int((time.monotonic() - start) * 1000)
        return {"status": "ok", "host": host, "port": str(port), "duration_ms": str(duration_ms)}
    with socket.create_connection((host, port), timeout=timeout_s):
        pass
    duration_ms = int((time.monotonic() - start) * 1000)
    return {"status": "ok", "host": host, "port": str(port), "duration_ms": str(duration_ms)}


def probe_dependencies(
    dsn_postgres: str,
    url_redis: str,
    timeout_s: float,
    *,
    registry: CollectorRegistry | None = None,
) -> dict[str, dict[str, str]]:
    registry = registry or REGISTRY
    attempts = _attempt_counter(registry)
    failures = _failure_counter(registry)

    dsn = sanitize_env_text(dsn_postgres)
    redis_url = sanitize_env_text(url_redis)
    if not dsn:
        raise ServiceError(
            "CONFIG_MISSING",
            "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است.",
            context={"variable": "DATABASE_URL"},
        )
    if not redis_url:
        raise ServiceError(
            "CONFIG_MISSING",
            "پیکربندی ناقص است؛ متغیر REDIS_URL خالی است.",
            context={"variable": "REDIS_URL"},
        )

    results: dict[str, dict[str, str]] = {}
    failures_seen: list[str] = []

    try:
        results["postgres"] = _probe_postgres(dsn, timeout_s)
    except Exception as exc:  # pragma: no cover - network failure is covered via monkeypatch
        reason = type(exc).__name__
        attempts.labels(dep="postgres", outcome="failure").inc()
        failures.labels(dep="postgres", reason=reason).inc()
        results["postgres"] = {"status": "error", "reason": reason}
        failures_seen.append("postgres")
    else:
        attempts.labels(dep="postgres", outcome="success").inc()

    try:
        results["redis"] = _probe_redis(redis_url, timeout_s)
    except Exception as exc:  # pragma: no cover - network failure is covered via monkeypatch
        reason = type(exc).__name__
        attempts.labels(dep="redis", outcome="failure").inc()
        failures.labels(dep="redis", reason=reason).inc()
        results["redis"] = {"status": "error", "reason": reason}
        failures_seen.append("redis")
    else:
        attempts.labels(dep="redis", outcome="success").inc()

    if failures_seen:
        raise DependencyNotReady(
            "سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند.",
            context={"failures": ",".join(sorted(failures_seen))},
        )
    return results


__all__ = ["plan_backoff", "probe_dependencies"]
