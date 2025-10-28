"""Shared fixtures for CI hardening tests."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Dict

import warnings

import pytest
from freezegun import freeze_time
from prometheus_client import CollectorRegistry

pytest_plugins = ("tests.fixtures.state", "tests.integration.conftest")

try:  # pragma: no cover - optional dependency guard
    from anyio.streams import memory as _anyio_memory

    _anyio_memory.MemoryObjectReceiveStream.__del__ = lambda self: None  # type: ignore[attr-defined]
    _anyio_memory.MemoryObjectSendStream.__del__ = lambda self: None  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - if anyio changes
    pass

from sma.ci_hardening.clock import Clock
from sma.ci_hardening.runtime import ensure_tehran_tz
from sma.ci_hardening.state import InMemoryStore


warnings.filterwarnings("ignore", category=pytest.PytestUnraisableExceptionWarning)
warnings.filterwarnings("ignore", category=ResourceWarning, module="anyio.streams.memory")


@pytest.fixture(scope="session")
def tehran_zone() -> Iterator[Clock]:
    """Provide the Tehran timezone clock for deterministic tests."""

    tz = ensure_tehran_tz()
    yield Clock(tz=tz)


@pytest.fixture()
def frozen_time(tehran_zone: Clock) -> Iterator[Clock]:
    """Freeze time for deterministic behaviour."""

    with freeze_time("2024-01-01T00:00:00+03:30"):
        yield tehran_zone


@pytest.fixture()
def collector_registry() -> Iterator[CollectorRegistry]:
    """Provide an isolated Prometheus registry per test."""

    registry = CollectorRegistry()
    yield registry


@pytest.fixture()
def clean_state() -> Iterator[InMemoryStore]:
    """Provide isolated key-value stores and ensure cleanup before/after tests."""

    namespace = f"test-{uuid.uuid4()}"
    store = InMemoryStore(namespace=namespace)
    store.flush()
    try:
        yield store
    finally:
        store.flush()


def get_debug_context(store: InMemoryStore) -> Dict[str, Any]:
    """Return a deterministic debug context for assertions."""

    return {
        "redis_keys": store.keys(),
        "namespace": store.namespace,
        "timestamp": time.time(),
    }


@pytest.fixture()
def debug_context(clean_state: InMemoryStore) -> Iterator[Dict[str, Any]]:
    """Yield debug context before and after a test."""

    before = get_debug_context(clean_state)
    yield before
    after = get_debug_context(clean_state)
    if after["redis_keys"]:
        print("DEBUG STATE:", json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2))
