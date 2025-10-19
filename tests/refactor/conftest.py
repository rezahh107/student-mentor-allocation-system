"""Fixtures for refactor import tool tests."""
from __future__ import annotations

import os
from typing import Dict, Generator

import fakeredis
import pytest
from prometheus_client import CollectorRegistry


@pytest.fixture()
def clean_state() -> Generator[Dict[str, object], None, None]:
    """Ensure Redis-like state and metrics registry are clean before and after each test."""
    # The project ships a deterministic FakeStrictRedis implementation under src/.
    redis_client = fakeredis.FakeStrictRedis()
    redis_client.flushdb()
    registry = CollectorRegistry()
    os.environ.pop("X_CORRELATION_ID", None)
    state = {"redis": redis_client, "registry": registry}
    yield state
    redis_client.flushdb()
    # Recreate registry to drop collectors deterministically without touching private APIs.
    state["registry"] = CollectorRegistry()


def get_debug_context(redis_client: fakeredis.FakeRedis) -> Dict[str, object]:
    """Return context payload to aid debugging when assertions fail."""
    return {
        "redis_keys": sorted(redis_client.keys("*")),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": DEFAULT_CLOCK,
        "middleware_order": ["RateLimit", "Idempotency", "Auth"],
    }


DEFAULT_CLOCK = "1403-01-01T00:00:00+03:30"
