from __future__ import annotations

import asyncio
from collections import deque

import pytest
from prometheus_client import CollectorRegistry

from src.phase7_release.runtime import GracefulShutdownController


@pytest.fixture
def clean_state():
    yield


@pytest.mark.asyncio
async def test_sigterm_drain_and_close(monkeypatch, clean_state):
    loop = asyncio.get_event_loop()
    registry = CollectorRegistry()
    drain_log = deque()

    controller = GracefulShutdownController(
        drain_timeout=0.5,
        loop=loop,
        clock=loop.time,
        sleep=asyncio.sleep,
        registry=registry,
    )

    async def cleanup_job() -> None:
        drain_log.append("cleanup")

    controller.register_cleanup(cleanup_job)
    await controller.initiate_shutdown(signum=15)
    assert list(drain_log) == ["cleanup"]
    assert list(registry.collect()) == []
