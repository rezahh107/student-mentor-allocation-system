"""Deterministic asyncio Redis substitute for offline test execution."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any, Dict, List, MutableMapping, Tuple


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return str(value).encode("utf-8")


class AsyncFakePipeline:
    """Very small subset of the Redis pipeline API."""

    def __init__(self, client: "AsyncFakeRedis") -> None:
        self._client = client
        self._commands: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
        self._executed = False

    async def __aenter__(self) -> "AsyncFakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.reset()
            return
        await self.execute()

    def watch(self, *_keys: str) -> None:  # pragma: no cover - compatibility no-op
        return None

    def multi(self) -> None:  # pragma: no cover - compatibility no-op
        return None

    def reset(self) -> None:
        self._commands.clear()
        self._executed = False

    async def execute(self) -> List[Any]:
        if self._executed:
            return []
        self._executed = True
        results: List[Any] = []
        for name, args, kwargs in list(self._commands):
            method = getattr(self._client, name)
            result = await method(*args, **kwargs)
            results.append(result)
        self._commands.clear()
        return results

    def _queue(self, name: str, *args: Any, **kwargs: Any) -> "AsyncFakePipeline":
        self._commands.append((name, args, kwargs))
        return self

    def set(self, *args: Any, **kwargs: Any) -> "AsyncFakePipeline":
        return self._queue("set", *args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> "AsyncFakePipeline":
        return self._queue("get", *args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> "AsyncFakePipeline":
        return self._queue("delete", *args, **kwargs)


class AsyncFakeRedis:
    """Minimal async Redis clone satisfying the subset used in tests."""

    def __init__(self, *, namespace: str | None = None, clock: callable | None = None) -> None:
        self.namespace = namespace or "sma:test:fakeredis"
        self._clock = clock or time.monotonic
        self._kv: MutableMapping[str, Tuple[bytes, float | None]] = {}
        self._zsets: MutableMapping[str, Dict[str, float]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    def pipeline(self, transaction: bool = True) -> AsyncFakePipeline:  # pragma: no cover - thin wrapper
        _ = transaction  # redis accepts the flag but ignores when unsupported
        return AsyncFakePipeline(self)

    async def set(self, name: str, value: Any, *, ex: int | None = None, nx: bool = False) -> bool:
        data = _to_bytes(value)
        expiry = self._expiry_seconds(ex)
        async with self._lock:
            self._purge()
            if nx and name in self._kv:
                stored, ttl = self._kv[name]
                if ttl is None or ttl > self._clock():
                    return False
            self._kv[name] = (data, expiry)
        return True

    async def get(self, name: str) -> bytes | None:
        async with self._lock:
            self._purge()
            entry = self._kv.get(name)
            return entry[0] if entry else None

    async def delete(self, *names: str) -> int:
        removed = 0
        async with self._lock:
            for name in names:
                if name in self._kv or name in self._zsets:
                    removed += 1
                self._kv.pop(name, None)
                self._zsets.pop(name, None)
        return removed

    async def expire(self, name: str, ttl: int) -> bool:
        async with self._lock:
            self._purge()
            if name not in self._kv and name not in self._zsets:
                return False
            if name in self._kv:
                value, _ = self._kv[name]
                self._kv[name] = (value, self._clock() + max(0, ttl))
            else:
                for member, score in list(self._zsets[name].items()):
                    self._zsets[name][member] = score
            return True

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        async with self._lock:
            self._purge()
            target = self._zsets[name]
            for member, score in mapping.items():
                target[member] = float(score)
        return len(mapping)

    async def zremrangebyscore(self, name: str, min: float, max: float) -> int:
        async with self._lock:
            self._purge()
            target = self._zsets.get(name)
            if not target:
                return 0
            removed = [member for member, score in target.items() if min <= score <= max]
            for member in removed:
                target.pop(member, None)
            if not target:
                self._zsets.pop(name, None)
            return len(removed)

    async def zcard(self, name: str) -> int:
        async with self._lock:
            self._purge()
            return len(self._zsets.get(name, {}))

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        _ = numkeys
        if not keys_and_args:
            return 0
        key = str(keys_and_args[0])
        async with self._lock:
            self._purge()
            entries = self._zsets.get(key)
            if not entries:
                return 0
            oldest = min(entries.values())
            return float(oldest)

    async def exists(self, name: str) -> bool:
        async with self._lock:
            self._purge()
            return name in self._kv or name in self._zsets

    async def flushdb(self) -> None:
        async with self._lock:
            self._kv.clear()
            self._zsets.clear()

    def _expiry_seconds(self, ttl: int | None) -> float | None:
        if ttl is None:
            return None
        return self._clock() + max(0, ttl)

    def _purge(self) -> None:
        now = self._clock()
        expired_keys = [name for name, (_, ttl) in self._kv.items() if ttl is not None and ttl <= now]
        for name in expired_keys:
            self._kv.pop(name, None)
        empty_sets = []
        for name, members in self._zsets.items():
            for member, score in list(members.items()):
                # Sorted set entries expire through explicit trim; keep deterministic ordering
                members[member] = float(score)
            if not members:
                empty_sets.append(name)
        for name in empty_sets:
            self._zsets.pop(name, None)


__all__ = ["AsyncFakeRedis", "AsyncFakePipeline"]

