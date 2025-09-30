"""Shared pytest fixtures respecting AGENTS determinism guidance."""

from __future__ import annotations

import importlib
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from prometheus_client import CollectorRegistry

import pytest


os.environ.setdefault("RUN_PERFORMANCE_SUITE", "1")


pytest_plugins = (
    "pytest_asyncio",
    "tests.audit_retention.conftest",
    "tests.auth.conftest",
    "tests.fixtures.state",
    "tests.fixtures.debug_context",
    "tests.fixtures.factories",
    "tests.ops.conftest",
    "tests.plugins.pytest_asyncio_compat",
    "tests.plugins.session_stats",
    "tests.uploads.conftest",
    "pytester",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("env", "Environment variables for deterministic testing.", type="linelist", default=[])
    try:
        parser.addini(
            "asyncio_default_fixture_loop_scope",
            "Default asyncio fixture loop scope registered for pytest-asyncio.",
            default="function",
        )
    except ValueError:
        # Already registered by pytest-asyncio; ignore to keep determinism.
        pass


def pytest_configure(config: pytest.Config) -> None:
    for item in config.getini("env"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


if os.environ.get("TZ") != "Asia/Tehran":
    os.environ["TZ"] = "Asia/Tehran"
    if hasattr(time, "tzset"):
        time.tzset()


_TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


@dataclass
class DeterministicClock:
    """Deterministic clock aligned with AGENTS.md::Determinism."""

    _current: datetime

    def __call__(self) -> datetime:
        return self._current

    def now(self) -> datetime:
        return self._current

    def tick(self, *, seconds: float = 0.0) -> datetime:
        delta = timedelta(seconds=seconds)
        self._current = self._current + delta
        return self._current

    def freeze(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=_TEHRAN_TZ)
        self._current = value.astimezone(_TEHRAN_TZ)
        return self._current


@dataclass(slots=True)
class RedisStateContext:
    client: Any
    namespace: str

    def key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    def debug(self) -> dict[str, object]:
        keys = sorted(str(key) for key in self.client.scan_iter(match=f"{self.namespace}:*"))
        return {"namespace": self.namespace, "keys": keys}

    def purge(self) -> None:
        _purge_namespace(self.client, self.namespace)


def _purge_namespace(client: Any, namespace: str) -> None:
    pattern = f"{namespace}:*"
    keys = [str(key) for key in client.scan_iter(match=pattern)]
    if keys:
        client.delete(*keys)


def _build_redis_client(url: str | None) -> Any:
    if url:
        import redis

        return redis.Redis.from_url(url, decode_responses=True)
    from src.fakeredis import FakeStrictRedis

    return FakeStrictRedis()


@pytest.fixture(scope="module", autouse=True)
def metrics_registry_guard() -> Iterator[CollectorRegistry]:
    """Reset the Prometheus CollectorRegistry per-module (AGENTS.md §8)."""

    modules_to_patch = (
        "prometheus_client",
        "prometheus_client.registry",
        "prometheus_client.core",
    )
    modules = [importlib.import_module(name) for name in modules_to_patch]
    originals: list[CollectorRegistry | None] = [getattr(module, "REGISTRY", None) for module in modules]
    new_registry = CollectorRegistry()
    for module in modules:
        setattr(module, "REGISTRY", new_registry)

    try:
        yield new_registry
    finally:
        collector_map = getattr(new_registry, "_collector_to_names", {})
        for collector in list(collector_map.keys()):
            try:
                new_registry.unregister(collector)
            except KeyError:  # pragma: no cover - defensive cleanup
                continue
        for module, original in zip(modules, originals):
            if original is not None:
                setattr(module, "REGISTRY", original)


@pytest.fixture()
def redis_state_guard() -> Iterator[RedisStateContext]:
    """Provide isolated Redis namespaces with cleanup before/after (AGENTS.md §8)."""

    url = os.getenv("STRICT_CI_REDIS_URL")
    namespace = f"import-to-sabt::{uuid.uuid4().hex}"
    client = _build_redis_client(url)
    _purge_namespace(client, namespace)
    context = RedisStateContext(client=client, namespace=namespace)
    try:
        yield context
    finally:
        context.purge()
        close = getattr(client, "close", None)
        if callable(close):  # pragma: no cover - redis-py only
            close()
        pool = getattr(client, "connection_pool", None)
        disconnect = getattr(pool, "disconnect", None)
        if callable(disconnect):  # pragma: no cover - redis-py only
            disconnect()

@pytest.fixture()
def clock() -> Iterator[DeterministicClock]:
    """Provide deterministic time control per AGENTS.md::Testing & CI Gates."""

    timeline = DeterministicClock(
        _current=datetime(2024, 1, 1, 0, 0, tzinfo=_TEHRAN_TZ)
    )
    try:
        yield timeline
    finally:
        timeline.freeze(datetime(2024, 1, 1, 0, 0, tzinfo=_TEHRAN_TZ))
