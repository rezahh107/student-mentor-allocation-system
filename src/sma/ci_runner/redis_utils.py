"""Redis hygiene helpers ensuring deterministic namespaces and cleanup."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

import redis
from prometheus_client import CollectorRegistry, Counter, Histogram
import prometheus_client.registry as prometheus_registry

try:  # pragma: no cover - optional dependency
    import fakeredis  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fakeredis = None

from .bootstrap import BootstrapError
from .logging_utils import bilingual_message, correlation_id, log_event

PERSIAN_REDIS_UNAVAILABLE = "اتصال به Redis برقرار نشد؛ سرویس Redis یا دسترسی شبکه را بررسی کنید."
PERSIAN_FLUSH_ERROR = "دستور FLUSH در میانهٔ اجرا مجاز نیست؛ به راهنمای Tailored v2.4 مراجعه کنید."

REDIS_TIMEOUT = float(os.getenv("CI_REDIS_TIMEOUT", "3"))


@dataclass(frozen=True)
class RedisHandle:
    client: "GuardedRedis"
    namespace: str
    using_fakeredis: bool
    registry: CollectorRegistry


class GuardedRedis:
    """Proxy around a redis client forbidding mid-run flush operations."""

    def __init__(self, client: redis.Redis):
        self._client = client
        self._allow_flush = False

    def suite_flush(self) -> None:
        self._allow_flush = True
        try:
            self._client.flushdb()
        finally:
            self._allow_flush = False

    def suite_flush_all(self) -> None:
        self._allow_flush = True
        try:
            self._client.flushall()
        finally:
            self._allow_flush = False

    def flushdb(self) -> None:  # pragma: no cover - enforced via tests
        raise BootstrapError(bilingual_message(PERSIAN_FLUSH_ERROR, "FLUSHDB mid-run is prohibited"))

    def flushall(self) -> None:  # pragma: no cover - enforced via tests
        raise BootstrapError(bilingual_message(PERSIAN_FLUSH_ERROR, "FLUSHALL mid-run is prohibited"))

    def __getattr__(self, item):
        return getattr(self._client, item)


def build_namespace(worker_id: str | None = None, timestamp_seed: str | None = None) -> str:
    worker = worker_id or os.getenv("PYTEST_XDIST_WORKER") or "gw0"
    base_seed = f"{worker}:{timestamp_seed or correlation_id()}"
    digest = hashlib.blake2b(base_seed.encode("utf-8"), digest_size=16).hexdigest()
    first, second = digest[:8], digest[8:14]
    return f"t:{worker}:{first}:{second}"


def _connect_real_redis() -> redis.Redis:
    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6379"))
    client = redis.Redis(host=host, port=port, db=int(os.getenv("REDIS_DB", "0")), socket_timeout=REDIS_TIMEOUT)
    client.ping()
    return client


def _connect_fakeredis() -> redis.Redis:
    if fakeredis is None:
        raise BootstrapError(bilingual_message(PERSIAN_REDIS_UNAVAILABLE, "fakeredis is not installed"))
    return fakeredis.FakeStrictRedis()


def _obtain_client() -> tuple[redis.Redis, bool]:
    try:
        client = _connect_real_redis()
        log_event("redis_real", backend="redis")
        return client, False
    except Exception:
        log_event("redis_real_failed", backend="redis")
        client = _connect_fakeredis()
        log_event("redis_fallback", backend="fakeredis")
        return client, True


def reset_prometheus_registry() -> CollectorRegistry:
    registry = CollectorRegistry()
    prometheus_registry.REGISTRY = registry
    return registry


@contextmanager
def redis_namespace(prefix: str | None = None) -> Generator[RedisHandle, None, None]:
    namespace = prefix or build_namespace()
    raw_client, using_fakeredis = _obtain_client()
    client = GuardedRedis(raw_client)

    registry = reset_prometheus_registry()
    metrics = {
        "suite_duration": Histogram(
            "ci_runner_suite_duration_seconds",
            "Duration of pytest suites",
            labelnames=("layer",),
            registry=registry,
        ),
        "retries": Counter(
            "ci_runner_retry_total",
            "Total retries executed",
            labelnames=("operation",),
            registry=registry,
        ),
    }
    for name, metric in metrics.items():
        setattr(redis_namespace, name, metric)

    handle = RedisHandle(client=client, namespace=namespace, using_fakeredis=using_fakeredis, registry=registry)

    client.suite_flush()
    try:
        yield handle
    finally:
        client.suite_flush()
        reset_prometheus_registry()


__all__ = [
    "RedisHandle",
    "GuardedRedis",
    "redis_namespace",
    "build_namespace",
    "reset_prometheus_registry",
]
