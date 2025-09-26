"""Embedded Redis stub used for deterministic smoke tests."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(slots=True)
class _RateState:
    tokens: float
    timestamp: float


class _Backend:
    """Shared in-memory backend emulating a subset of Redis operations."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._rate: dict[str, _RateState] = {}
        self._lock = threading.RLock()

    def _purge_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, expiry in self._expiry.items() if expiry <= now]
        for key in expired:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            self._rate.pop(key, None)

    def flushdb(self) -> None:
        with self._lock:
            self._data.clear()
            self._expiry.clear()
            self._rate.clear()

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool:
        with self._lock:
            self._purge_locked()
            if nx and key in self._data:
                return False
            self._data[key] = value
            if px is not None:
                self._expiry[key] = time.monotonic() + (px / 1000.0)
            else:
                self._expiry.pop(key, None)
            return True

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_locked()
            return self._data.get(key)

    def delete(self, key: str) -> int:
        with self._lock:
            self._purge_locked()
            removed = 1 if key in self._data else 0
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            self._rate.pop(key, None)
            return removed

    def expire(self, key: str, seconds: int) -> bool:
        with self._lock:
            self._purge_locked()
            if key not in self._data:
                return False
            self._expiry[key] = time.monotonic() + max(seconds, 0)
            return True

    def pttl(self, key: str) -> int:
        with self._lock:
            self._purge_locked()
            expiry = self._expiry.get(key)
            if key not in self._data:
                return -2
            if expiry is None:
                return -1
            remaining = expiry - time.monotonic()
            return int(max(0.0, remaining) * 1000)

    def incr(self, key: str) -> int:
        with self._lock:
            self._purge_locked()
            current = int(self._data.get(key, "0")) + 1
            self._data[key] = str(current)
            return current

    def keys(self, pattern: str = "*") -> Iterable[str]:
        with self._lock:
            self._purge_locked()
            if pattern == "*":
                return list(self._data.keys())
            return [key for key in self._data if key.startswith(pattern.rstrip("*"))]

    # Lua script emulation -------------------------------------------------
    def run_script(self, script: str, keys: list[str], args: list[Any]) -> Any:
        if "redis.call('GET', KEYS[1]) == ARGV[1]" in script:
            lock_key = keys[0]
            token = args[0]
            with self._lock:
                self._purge_locked()
                if self._data.get(lock_key) == token:
                    self._data.pop(lock_key, None)
                    self._expiry.pop(lock_key, None)
                    return 1
            return 0
        if "redis.call('SET', record_key, payload, 'EX', ttl)" in script:
            record_key, lock_key, fence_key = keys
            payload, ttl, token, fence = args
            ttl_seconds = int(float(ttl))
            fence_value = int(float(fence))
            with self._lock:
                self._purge_locked()
                if self._data.get(lock_key) != token:
                    return 0
                self._data[record_key] = str(payload)
                self._expiry[record_key] = time.monotonic() + max(ttl_seconds, 1)
                self._data[fence_key] = str(fence_value)
                return 1
        if "redis.call('HMGET', key, 'tokens', 'timestamp')" in script:
            key = keys[0]
            capacity, refill_rate, now, ttl = map(float, args)
            ttl_seconds = max(int(ttl), 1)
            with self._lock:
                self._purge_locked()
                state = self._rate.get(key)
                if state is None:
                    tokens = capacity
                    last = now
                else:
                    tokens = state.tokens
                    last = state.timestamp
                    delta = max(0.0, now - last)
                    tokens = min(capacity, tokens + delta * refill_rate)
                allowed = 0
                remaining = tokens
                if tokens >= 1:
                    allowed = 1
                    tokens -= 1
                    remaining = tokens
                if refill_rate <= 0:
                    retry_after = float(ttl_seconds)
                else:
                    retry_after = 0.0 if allowed else max(0.0, (1 - tokens) / refill_rate)
                self._rate[key] = _RateState(tokens=tokens, timestamp=now)
                self._expiry[key] = time.monotonic() + ttl_seconds
                self._data[key] = json.dumps({"tokens": tokens, "timestamp": now})
                return [allowed, remaining, retry_after]
        raise NotImplementedError("script not supported by redis stub")


class _EmbeddedScript:
    def __init__(self, backend: _Backend, script: str) -> None:
        self._backend = backend
        self._script = script

    async def __call__(self, *, keys: list[str] | None = None, args: list[Any] | None = None) -> Any:
        return self._backend.run_script(self._script, keys or [], args or [])


_BACKENDS: dict[str, _Backend] = {}
_LOCK = threading.Lock()


def _get_backend(url: str) -> _Backend:
    with _LOCK:
        backend = _BACKENDS.get(url)
        if backend is None:
            backend = _Backend()
            _BACKENDS[url] = backend
        return backend


class AsyncClient:
    def from_url(self, url: str, *, encoding: str | None = None, decode_responses: bool = True):
        backend = _get_backend(url)
        return _AsyncRedisClient(backend, decode_responses=decode_responses)


class _AsyncRedisClient:
    def __init__(self, backend: _Backend, *, decode_responses: bool) -> None:
        self._backend = backend
        self._decode = decode_responses

    async def get(self, key: str) -> str | bytes | None:
        value = self._backend.get(key)
        if value is None:
            return None
        return value if self._decode else value.encode("utf-8")

    async def set(self, key: str, value: Any, *, nx: bool = False, px: int | None = None) -> bool:
        stored = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        return self._backend.set(key, stored, nx=nx, px=px)

    async def delete(self, key: str) -> int:
        return self._backend.delete(key)

    async def expire(self, key: str, seconds: int) -> bool:
        return self._backend.expire(key, seconds)

    async def pttl(self, key: str) -> int:
        return self._backend.pttl(key)

    async def incr(self, key: str) -> int:
        return self._backend.incr(key)

    def register_script(self, script: str) -> _EmbeddedScript:
        return _EmbeddedScript(self._backend, script)

    async def flushdb(self) -> None:
        self._backend.flushdb()

    async def ping(self) -> bool:
        return self._backend.ping()

    async def aclose(self) -> None:  # pragma: no cover - symmetry with redis client
        return None


class _SyncRedisClient:
    def __init__(self, backend: _Backend) -> None:
        self._backend = backend

    def set(self, key: str, value: Any, ex: int | None = None, px: int | None = None, nx: bool = False) -> bool:
        stored = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        ttl = px if px is not None else (ex * 1000 if ex is not None else None)
        return self._backend.set(key, stored, nx=nx, px=ttl)

    def get(self, key: str) -> str | None:
        return self._backend.get(key)

    def delete(self, key: str) -> int:
        return self._backend.delete(key)

    def incr(self, key: str) -> int:
        return self._backend.incr(key)

    def expire(self, key: str, seconds: int) -> bool:
        return self._backend.expire(key, seconds)

    def pttl(self, key: str) -> int:
        return self._backend.pttl(key)

    def keys(self, pattern: str = "*") -> Iterable[str]:
        return self._backend.keys(pattern)

    def ping(self) -> bool:
        return self._backend.ping()

    def flushdb(self) -> None:
        self._backend.flushdb()

    def close(self) -> None:  # pragma: no cover - symmetry with redis client
        return None

    @classmethod
    def from_url(cls, url: str) -> "_SyncRedisClient":
        return cls(_get_backend(url))


class _RedisNamespace:
    Redis = _SyncRedisClient

    @staticmethod
    def from_url(url: str) -> _SyncRedisClient:
        return _SyncRedisClient(_get_backend(url))


async_client = AsyncClient()
redis_sync = _RedisNamespace()


class _Exceptions:
    ConnectionError = RuntimeError


redis_sync.exceptions = _Exceptions()  # type: ignore[attr-defined]

__all__ = [
    "async_client",
    "redis_sync",
]
