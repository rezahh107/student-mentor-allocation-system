from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import anyio

from ops.replica_adapter import ReplicaAdapter


class FrozenClock:
    def __init__(self) -> None:
        self.calls = 0
        self._moment = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))

    def now(self) -> dt.datetime:
        self.calls += 1
        return self._moment


class SingleRowConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    async def fetch(self, query: str, *args: object):
        return [self._row]


def test_injected_clock_used():
    async def _run() -> None:
        clock = FrozenClock()

        async def _connection_factory():
            await asyncio.sleep(0)
            return SingleRowConnection({"center_id": "123"})

        adapter = ReplicaAdapter(_connection_factory, clock)
        result = await adapter.fetch_exports()
        assert result.generated_at == clock._moment
        assert clock.calls >= 2

    anyio.run(_run)
