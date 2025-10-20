from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable, Iterable

from psycopg import AsyncConnection
from redis.asyncio import Redis

from sma.phase6_import_to_sabt.app.probes import ProbeResult


async def _retry(
    func: Callable[[], Awaitable[None]],
    *,
    attempts: int,
    base_delay: float,
    jitter: Iterable[float] | None,
    sleeper: Callable[[float], Awaitable[None]],
) -> str | None:
    errors: list[str] = []
    jitter_iter = itertools.cycle(jitter or (0.0,))
    for attempt in range(1, attempts + 1):
        try:
            await func()
            return None
        except Exception as exc:  # pragma: no cover - defensive fallback
            errors.append(str(exc))
            if attempt == attempts:
                return errors[-1]
            delay = base_delay * (2** (attempt - 1)) + next(jitter_iter)
            await sleeper(delay)
    return errors[-1] if errors else None


def build_redis_probe(
    dsn: str,
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    jitter: Iterable[float] | None = None,
    client_factory: Callable[[str], Redis] | None = None,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> Callable[[float], Awaitable[ProbeResult]]:
    client_factory = client_factory or (lambda url: Redis.from_url(url, decode_responses=True))
    sleeper = sleeper or asyncio.sleep

    async def probe(timeout: float) -> ProbeResult:
        async def operation() -> None:
            client = client_factory(dsn)
            try:
                await asyncio.wait_for(client.ping(), timeout)
            finally:
                await client.close()

        last_error = await _retry(
            operation,
            attempts=attempts,
            base_delay=base_delay,
            jitter=jitter,
            sleeper=sleeper,
        )
        healthy = last_error is None
        return ProbeResult(component="redis", healthy=healthy, detail=last_error)

    return probe


def build_postgres_probe(
    dsn: str,
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    jitter: Iterable[float] | None = None,
    connection_factory: Callable[[str], Awaitable[AsyncConnection]] | None = None,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> Callable[[float], Awaitable[ProbeResult]]:
    connection_factory = connection_factory or (lambda url: AsyncConnection.connect(url))
    sleeper = sleeper or asyncio.sleep

    async def probe(timeout: float) -> ProbeResult:
        async def operation() -> None:
            connection = await asyncio.wait_for(connection_factory(dsn), timeout)
            async with connection as conn:
                await asyncio.wait_for(conn.execute("SELECT 1"), timeout)

        last_error = await _retry(
            operation,
            attempts=attempts,
            base_delay=base_delay,
            jitter=jitter,
            sleeper=sleeper,
        )
        healthy = last_error is None
        return ProbeResult(component="postgres", healthy=healthy, detail=last_error)

    return probe


__all__ = ["build_redis_probe", "build_postgres_probe"]
