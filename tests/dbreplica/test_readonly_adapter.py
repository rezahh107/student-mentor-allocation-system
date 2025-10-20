from __future__ import annotations

import asyncio
import datetime as dt

import anyio
import pytest

from sma.ops.replica_adapter import ReplicaAdapter, ReplicaTimeoutError


class FrozenClock:
    def now(self) -> dt.datetime:
        return dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)


class HangingConnection:
    async def fetch(self, query: str, *args: object):
        await asyncio.sleep(1)
        return []


def test_replica_timeout_persian_error():
    async def _run() -> None:
        async def factory():
            await asyncio.sleep(0)
            return HangingConnection()

        adapter = ReplicaAdapter(factory, FrozenClock(), timeout_seconds=0.01, attempts=1)

        with pytest.raises(ReplicaTimeoutError) as exc:
            await adapter.fetch_exports()
        assert "خطای اتصال به مخزن" in str(exc.value)

    anyio.run(_run)
