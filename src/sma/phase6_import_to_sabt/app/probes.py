from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

import anyio
from psycopg import AsyncConnection
from redis.asyncio import Redis


@dataclass
class ProbeResult:
    component: str
    healthy: bool
    detail: str | None = None


class AsyncProbe(Protocol):
    async def __call__(self, timeout: float) -> ProbeResult:
        ...


def redis_probe(redis: Redis) -> AsyncProbe:
    async def _probe(timeout: float) -> ProbeResult:
        try:
            async with anyio.fail_after(timeout):
                await redis.ping()
            return ProbeResult(component="redis", healthy=True)
        except Exception as exc:  # pragma: no cover - defensive
            return ProbeResult(component="redis", healthy=False, detail=str(exc))

    return _probe


def db_probe(conn_factory: Callable[[], Awaitable[AsyncConnection]]) -> AsyncProbe:
    async def _probe(timeout: float) -> ProbeResult:
        try:
            async with anyio.fail_after(timeout):
                async with await conn_factory() as conn:
                    await conn.execute("SELECT 1")
            return ProbeResult(component="postgres", healthy=True)
        except Exception as exc:  # pragma: no cover - defensive
            return ProbeResult(component="postgres", healthy=False, detail=str(exc))

    return _probe


__all__ = ["ProbeResult", "AsyncProbe", "redis_probe", "db_probe"]
