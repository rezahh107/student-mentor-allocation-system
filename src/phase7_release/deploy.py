"""Deployment helpers for zero-downtime rollouts."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .atomic import atomic_write
from .hashing import sha256_bytes


@dataclass(slots=True)
class ReadinessState:
    cache_warm: bool = False
    dependencies: dict[str, bool] = field(default_factory=dict)
    last_errors: dict[str, str] = field(default_factory=dict)

    def record(self, name: str, healthy: bool, *, error: str | None = None) -> None:
        self.dependencies[name] = healthy
        if error:
            self.last_errors[name] = error
        elif name in self.last_errors:
            del self.last_errors[name]


class CircuitBreaker:
    """Simple deterministic circuit breaker with jitter-free semantics."""

    def __init__(
        self,
        *,
        clock: Callable[[], float],
        failure_threshold: int = 3,
        reset_timeout: float = 5.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._clock = clock
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self._state == "open" and self._clock() - self._opened_at >= self._reset_timeout:
            self._state = "half-open"
            return True
        return self._state != "open"

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._state = "open"
            self._opened_at = self._clock()

    @property
    def state(self) -> str:
        return self._state


class ReadinessGate:
    """Enforce readiness gating semantics for blue/green rollouts."""

    def __init__(
        self,
        *,
        clock: Callable[[], float],
        readiness_timeout: float = 30.0,
    ) -> None:
        self._clock = clock
        self._timeout = readiness_timeout
        self._state = ReadinessState()
        self._started_at = clock()

    def record_cache_warm(self) -> None:
        self._state.cache_warm = True

    def record_dependency(self, *, name: str, healthy: bool, error: str | None = None) -> None:
        self._state.record(name, healthy, error=error)

    def ready(self) -> bool:
        if not self._state.cache_warm:
            return False
        if not self._state.dependencies:
            return False
        if not all(self._state.dependencies.values()):
            return False
        return True

    def assert_post_allowed(self, *, correlation_id: str) -> None:
        if self.ready():
            return
        pending = [name for name, healthy in sorted(self._state.dependencies.items()) if not healthy]
        if not self._state.cache_warm:
            pending.insert(0, "cache")
        context = {
            "rid": correlation_id,
            "op": "post_gate",
            "namespace": "deploy.readiness",
            "path": "/",
            "pending": pending,
            "last_error": {key: self._state.last_errors.get(key) for key in pending if key in self._state.last_errors},
        }
        if self._clock() - self._started_at > self._timeout:
            raise RuntimeError(f"READINESS_TIMEOUT: {json.dumps(context, ensure_ascii=False)}")
        raise RuntimeError(f"POST_BLOCKED: {json.dumps(context, ensure_ascii=False)}")

    def allow_get(self) -> bool:
        return True


def get_debug_context(
    *,
    redis_keys: Callable[[], list[str]] | None = None,
    rate_limit_state: Callable[[], dict[str, object]] | None = None,
    middleware_chain: Callable[[], list[str]] | None = None,
    env_fetcher: Callable[[str, str], str] | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    now = clock() if clock is not None else time.time()
    return {
        "redis_keys": [] if redis_keys is None else sorted(redis_keys()),
        "rate_limit_state": {} if rate_limit_state is None else rate_limit_state(),
        "middleware_order": [] if middleware_chain is None else middleware_chain(),
        "env": (env_fetcher or os.getenv)("GITHUB_ACTIONS", "local"),
        "timestamp": now,
    }


class FileLockTimeout(RuntimeError):
    pass


@contextmanager
def file_lock(
    path: Path,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    timeout: float = 10.0,
) -> Iterator[None]:
    path = Path(path)
    deadline = clock() + timeout
    attempt = 0
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            break
        except FileExistsError:
            attempt += 1
            if clock() > deadline:
                raise FileLockTimeout(f"قفل فایل در {path} تمام شد")
            backoff = min(0.05 * (2 ** (attempt - 1)), 0.5)
            jitter_seed = sha256_bytes(f"{path}:{attempt}".encode("utf-8"))
            jitter = (int(jitter_seed[:8], 16) / float(0xFFFFFFFF)) * 0.05
            sleep(backoff + jitter)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class HandoffResult:
    build_id: str
    previous_target: Path | None
    current_target: Path


class ZeroDowntimeHandoff:
    """Coordinate blue/green handoffs using atomic symlink swaps."""

    def __init__(
        self,
        *,
        releases_dir: Path,
        lock_file: Path,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._releases_dir = Path(releases_dir)
        self._lock_file = Path(lock_file)
        self._clock = clock
        self._sleep = sleep
        self._releases_dir.mkdir(parents=True, exist_ok=True)

    def promote(self, *, build_id: str, source: Path) -> HandoffResult:
        handoff_state = self._releases_dir / "handoff.json"
        previous_target = None
        current_symlink = self._releases_dir / "current"
        previous_symlink = self._releases_dir / "previous"
        with file_lock(self._lock_file, clock=self._clock, sleep=self._sleep):
            if current_symlink.exists():
                previous_target = current_symlink.resolve()
            _atomic_symlink_swap(current_symlink, previous_symlink, source)
            payload = {
                "build_id": build_id,
                "source": str(source),
                "timestamp": self._clock(),
                "rid": sha256_bytes(build_id.encode("utf-8"))[:12],
            }
            atomic_write(handoff_state, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return HandoffResult(build_id=build_id, previous_target=previous_target, current_target=source)

    def rollback(self) -> HandoffResult:
        handoff_state = self._releases_dir / "handoff.json"
        current_symlink = self._releases_dir / "current"
        previous_symlink = self._releases_dir / "previous"
        with file_lock(self._lock_file, clock=self._clock, sleep=self._sleep):
            if not previous_symlink.exists():
                raise RuntimeError("ROLLBACK_UNAVAILABLE")
            previous_target = current_symlink.resolve() if current_symlink.exists() else None
            target = previous_symlink.resolve()
            _atomic_symlink_swap(current_symlink, previous_symlink, target)
            payload = {
                "build_id": target.name,
                "source": str(target),
                "rollback": True,
                "timestamp": self._clock(),
                "rid": sha256_bytes(str(target).encode("utf-8"))[:12],
            }
            atomic_write(handoff_state, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            return HandoffResult(build_id=target.name, previous_target=previous_target, current_target=target)


def _atomic_symlink_swap(current: Path, previous: Path, target: Path) -> None:
    target = Path(target)
    if current.exists() or current.is_symlink():
        resolved = current.resolve()
        temp_previous = previous.with_suffix(".tmp")
        os.replace(current, temp_previous)
        os.replace(temp_previous, previous)
        previous_target = resolved
    else:
        previous_target = None
    temp_link = current.with_suffix(".new")
    if temp_link.exists():
        temp_link.unlink()
    os.symlink(target, temp_link)
    os.replace(temp_link, current)
    if previous_target is None and previous.exists():
        previous.unlink()


__all__ = [
    "ReadinessGate",
    "ZeroDowntimeHandoff",
    "HandoffResult",
    "file_lock",
    "FileLockTimeout",
    "CircuitBreaker",
    "get_debug_context",
]
