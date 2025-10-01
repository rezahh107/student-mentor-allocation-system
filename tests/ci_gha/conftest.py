from __future__ import annotations

import os
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict

import pytest


class _FakeRedisClient:
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def flushdb(self) -> None:
        self._store.clear()

    def keys(self, pattern: str = "*") -> list[str]:
        return list(self._store.keys())


class _FakeDBSession:
    def rollback(self) -> None:  # pragma: no cover - simple stub
        return None


redis_client = _FakeRedisClient()
db_session = _FakeDBSession()
_rate_limit_events: Deque[str] = deque(maxlen=16)


def clear_rate_limiters() -> None:
    _rate_limit_events.clear()


def get_rate_limit_info() -> dict[str, Any]:
    return {"events": list(_rate_limit_events)}


def get_recent_logs() -> list[str]:
    return ["log:ok"]


def get_middleware_chain() -> list[str]:
    return ["RateLimitMiddleware", "IdempotencyMiddleware"]


def get_debug_context() -> dict[str, Any]:  # pragma: no cover - debugging aid
    return {
        "redis_keys": redis_client.keys("*"),
        "rate_limit_state": get_rate_limit_info(),
        "middleware_order": get_middleware_chain(),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": time.time(),
    }


@pytest.fixture
def clean_state(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    redis_client.flushdb()
    db_session.rollback()
    clear_rate_limiters()

    monotonic_steps = iter(float(x) / 10 for x in range(1, 1_000))

    def fake_monotonic() -> float:
        return next(monotonic_steps)

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    yield lambda: None

    redis_client.flushdb()
    clear_rate_limiters()


@dataclass
class RetryConfig:
    attempts: int = 3
    base_delay: float = 0.01


@pytest.fixture
def retry_call(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[], Any], RetryConfig], Any]:
    def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(time, "sleep", fake_sleep)

    def _retry(func: Callable[[], Any], config: RetryConfig | None = None) -> Any:
        cfg = config or RetryConfig()
        last_error: Exception | None = None
        for attempt in range(cfg.attempts):
            try:
                return func()
            except Exception as exc:  # pragma: no cover - error path
                last_error = exc
                jitter = random.uniform(0, cfg.base_delay)
                time.sleep(cfg.base_delay * (attempt + 1) + jitter)
        if last_error:
            raise last_error
        raise AssertionError("retry_call reached unreachable state")

    return _retry
