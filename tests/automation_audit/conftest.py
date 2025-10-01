from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Callable

import fakeredis
import pytest
from prometheus_client import CollectorRegistry

from automation_audit.metrics import build_metrics


@pytest.fixture
def redis_client() -> Iterator[fakeredis.FakeStrictRedis]:
    client = fakeredis.FakeStrictRedis()
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture
def metrics_registry() -> CollectorRegistry:
    return CollectorRegistry()


@pytest.fixture
def metrics(metrics_registry):
    return build_metrics(metrics_registry)


@pytest.fixture
def frozen_clock(monkeypatch):
    value = 1700000000.0

    def clock() -> float:
        return value

    monkeypatch.setattr("time.time", lambda: value)
    return clock
