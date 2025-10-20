"""Minimal in-repo stand-in for :mod:`fakeredis`.

The real dependency pulls a large transitive graph that is unavailable within
this execution environment.  The test-suite only relies on a tiny subset of the
API provided by :class:`fakeredis.FakeStrictRedis`, so we implement a compact and
fully deterministic drop-in replacement.  The behaviour mirrors redis-py closely
enough for our integration tests (idempotency store, rate-limiter, uploads
service) while remaining thread-safe and free from external services.
"""
from __future__ import annotations

import fnmatch
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Mapping, Optional

__all__ = ["FakeStrictRedis"]


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return str(value).encode("utf-8")


class _Pipeline:
    """Very small pipeline implementation used by the fake client."""

    def __init__(self, client: "FakeStrictRedis") -> None:
        self._client = client
        self._commands: List[tuple[str, tuple, dict]] = []
        self._executed = False
        self._lock = threading.RLock()

    # Context-manager protocol -------------------------------------------------
    def __enter__(self) -> "_Pipeline":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.reset()
        else:
            self.execute()

    # Redis pipeline API -------------------------------------------------------
    def watch(self, *keys: str) -> None:  # pragma: no cover - compatibility no-op
        return None

    def multi(self) -> None:  # pragma: no cover - compatibility no-op
        return None

    def reset(self) -> None:
        with self._lock:
            self._commands.clear()
            self._executed = False

    def execute(self) -> List[Any]:
        with self._lock:
            if self._executed:
                return []
            self._executed = True
            results: List[Any] = []
            for name, args, kwargs in self._commands:
                method = getattr(self._client, name)
                results.append(method(*args, **kwargs))
            self._commands.clear()
            return results

    # Command registration -----------------------------------------------------
    def _register(self, name: str, *args, **kwargs):
        self._commands.append((name, args, kwargs))
        return self

    def set(self, *args, **kwargs):
        return self._register("set", *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._register("get", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._register("delete", *args, **kwargs)

    def hset(self, *args, **kwargs):
        return self._register("hset", *args, **kwargs)

    def hgetall(self, *args, **kwargs):
        return self._register("hgetall", *args, **kwargs)


class FakeStrictRedis:
    """Very small in-memory Redis replacement for tests."""

    def __init__(self) -> None:
        self._values: Dict[str, bytes] = {}
        self._hashes: Dict[str, Dict[bytes, bytes]] = defaultdict(dict)
        self._expires: Dict[str, Optional[float]] = {}
        self._lock = threading.RLock()

    # Utility ------------------------------------------------------------------
    def _purge(self) -> None:
        now = time.time()
        expired = [key for key, ts in self._expires.items() if ts is not None and ts <= now]
        for key in expired:
            self._values.pop(key, None)
            self._hashes.pop(key, None)
            self._expires.pop(key, None)

    def _ttl_seconds(self, expire: Optional[float]) -> int:
        if expire is None:
            return -1
        remaining = int(round(expire - time.time()))
        return remaining if remaining >= 0 else -2

    # Basic key-value ----------------------------------------------------------
    def set(self, key: str, value: Any, ex: int | None = None, px: int | None = None, nx: bool = False) -> bool:
        with self._lock:
            self._purge()
            if nx and key in self._values:
                return False
            ttl = None
            if px is not None:
                ttl = time.time() + (px / 1000)
            elif ex is not None:
                ttl = time.time() + ex
            self._values[key] = _to_bytes(value)
            self._expires[key] = ttl
            return True

    def setnx(self, key: str, value: Any, ex: int | None = None) -> bool:
        return self.set(key, value, ex=ex, nx=True)

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            self._purge()
            return self._values.get(key)

    def delete(self, *keys: str) -> int:
        removed = 0
        with self._lock:
            for key in keys:
                if key in self._values or key in self._hashes:
                    removed += 1
                self._values.pop(key, None)
                self._hashes.pop(key, None)
                self._expires.pop(key, None)
        return removed

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            self._purge()
            current = int(self._values.get(key, b"0") or 0)
            current += amount
            self._values[key] = str(current).encode("utf-8")
            return current

    def expire(self, key: str, ttl: int) -> bool:
        with self._lock:
            if key not in self._values and key not in self._hashes:
                return False
            self._expires[key] = time.time() + ttl
            return True

    def ttl(self, key: str) -> int:
        with self._lock:
            self._purge()
            if key not in self._values and key not in self._hashes:
                return -2
            return self._ttl_seconds(self._expires.get(key))

    def scan_iter(self, match: str = "*") -> Iterator[str]:
        with self._lock:
            self._purge()
            for key in list({*self._values.keys(), *self._hashes.keys()}):
                if fnmatch.fnmatch(key, match):
                    yield key

    def keys(self, pattern: str = "*") -> List[str]:
        return list(self.scan_iter(pattern))

    def flushall(self) -> None:
        self.flushdb()

    def flushdb(self) -> None:
        with self._lock:
            self._values.clear()
            self._hashes.clear()
            self._expires.clear()

    # Hash operations ----------------------------------------------------------
    def hset(self, key: str, mapping: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> int:
        if mapping is None:
            mapping = {}
        if kwargs:
            mapping = {**mapping, **kwargs}
        with self._lock:
            self._purge()
            dest = self._hashes.setdefault(key, {})
            updated = 0
            for field, value in mapping.items():
                bfield = _to_bytes(field)
                dest_value = _to_bytes(value)
                if dest.get(bfield) != dest_value:
                    updated += 1
                dest[bfield] = dest_value
            return updated

    def hgetall(self, key: str) -> Dict[bytes, bytes]:
        with self._lock:
            self._purge()
            return dict(self._hashes.get(key, {}))

    # Scripting ----------------------------------------------------------------
    def register_script(self, func) -> Any:  # pragma: no cover - not used in tests
        raise NotImplementedError("register_script is not supported in FakeStrictRedis")

    # Context helpers ----------------------------------------------------------
    def pipeline(self, transaction: bool = True):  # pragma: no cover - transaction ignored
        return _Pipeline(self)

    # Debug --------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"FakeStrictRedis(values={self._values}, hashes={self._hashes})"
