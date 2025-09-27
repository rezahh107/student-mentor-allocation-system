from __future__ import annotations

import asyncio

import pytest

from phase6_import_to_sabt.probes.factories import build_postgres_probe, build_redis_probe


class FakeRedis:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.pings = 0
        self.closed = False

    async def ping(self) -> None:
        self.pings += 1
        if self.pings <= self.fail_times:
            raise RuntimeError("redis-failure")

    async def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.executed = False

    async def execute(self, query: str) -> None:
        self.executed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_readyz_real_redis_probe():
    fake = FakeRedis()
    probe = build_redis_probe(
        "redis://localhost",
        client_factory=lambda _: fake,
        sleeper=lambda _: asyncio.sleep(0),
    )
    result = await probe(0.1)
    assert result.healthy
    assert fake.closed


@pytest.mark.asyncio
async def test_readyz_real_postgres_probe():
    connection = FakeConnection()

    async def connector(_):
        return connection

    probe = build_postgres_probe("postgres://", connection_factory=connector, sleeper=lambda _: asyncio.sleep(0))
    result = await probe(0.1)
    assert result.healthy
    assert connection.executed


@pytest.mark.asyncio
async def test_probe_retry_backoff_deterministic():
    fake = FakeRedis(fail_times=2)
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    probe = build_redis_probe(
        "redis://localhost",
        attempts=3,
        base_delay=0.05,
        jitter=[0.01, 0.02],
        client_factory=lambda _: fake,
        sleeper=sleeper,
    )
    result = await probe(0.1)
    assert result.healthy
    assert delays == pytest.approx([0.06, 0.12], rel=1e-9)
