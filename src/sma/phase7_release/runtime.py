"""Runtime hardening helpers for ImportToSabt."""
from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from prometheus_client import CollectorRegistry


@dataclass
class GracefulShutdownController:
    """Coordinate graceful shutdown triggered by POSIX signals."""

    drain_timeout: float
    loop: asyncio.AbstractEventLoop
    clock: Callable[[], float]
    sleep: Callable[[float], Awaitable[None]]
    registry: CollectorRegistry
    _cleanup_handlers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    _signal_handlers: dict[int, Callable[[int, object | None], None]] = field(default_factory=dict)
    _drain_event: asyncio.Event = field(default_factory=asyncio.Event)

    def register_cleanup(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._cleanup_handlers.append(handler)

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            def _handler(signum: int, frame: object | None = None, *, _sig=sig) -> None:
                asyncio.run_coroutine_threadsafe(self.initiate_shutdown(signum=_sig), self.loop)
            self._signal_handlers[sig] = _handler
            signal.signal(sig, _handler)

    async def initiate_shutdown(self, *, signum: int) -> None:
        if self._drain_event.is_set():
            return
        self._drain_event.set()
        deadline = self.clock() + self.drain_timeout
        for handler in list(self._cleanup_handlers):
            if self.clock() > deadline:
                break
            await handler()
        while self.clock() < deadline:
            await self.sleep(0.05)
            if not self.loop.is_running():
                break
        cleared = getattr(self.registry, "clear", None)
        if callable(cleared):
            cleared()
        else:  # pragma: no cover - fallback for older prometheus_client versions
            self.registry._collector_to_names.clear()
            self.registry._names_to_collectors.clear()

    async def wait_for_shutdown(self) -> None:
        await self._drain_event.wait()


async def dependency_probe(*, redis_ping: Callable[[], Awaitable[bool]], db_check: Callable[[], Awaitable[bool]]) -> bool:
    redis_ok, db_ok = await asyncio.gather(redis_ping(), db_check())
    return redis_ok and db_ok


__all__ = ["GracefulShutdownController", "dependency_probe"]
