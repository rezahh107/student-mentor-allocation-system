from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Callable, Dict, TypeVar

import pytest

T = TypeVar("T")

_STATE_REGISTRY: set[str] = set()


def _compute_delay(namespace: str, attempt: int, base_delay: float) -> float:
    seed = f"{namespace}:{attempt}".encode("utf-8")
    digest = hashlib.blake2b(seed, digest_size=4).digest()
    jitter_fraction = int.from_bytes(digest, "big") / 0xFFFFFFFF
    return base_delay * (2 ** (attempt - 1)) + jitter_fraction * base_delay


def _debug_context(namespace: str, attempts: int, delays: tuple[float, ...]) -> Dict[str, Any]:
    return {
        "namespace": namespace,
        "attempts": attempts,
        "delays": delays,
        "state_registry": sorted(_STATE_REGISTRY),
        "middleware_chain": ("RateLimit", "Idempotency", "Auth"),
        "env": "ci",
        "timestamp": time.time(),
    }


@pytest.fixture
def clock_test_context() -> Dict[str, Any]:
    namespace = f"clock-tests::{uuid.uuid4()}"
    if namespace in _STATE_REGISTRY:  # pragma: no cover - defensive
        raise RuntimeError("duplicated namespace detected; state cleanup failed")

    _STATE_REGISTRY.add(namespace)
    attempts_observed = 0
    delays: list[float] = []
    cleanup_log: list[str] = []

    def retry(operation: Callable[[], T], *, max_attempts: int = 3, base_delay: float = 0.01) -> T:
        nonlocal attempts_observed
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            attempts_observed = max(attempts_observed, attempt)
            try:
                return operation()
            except Exception as exc:  # pragma: no cover - controlled via caller assertions
                last_error = exc
                delays.append(_compute_delay(namespace, attempt, base_delay))
                if attempt == max_attempts:
                    debug = _debug_context(namespace, attempts_observed, tuple(delays))
                    raise AssertionError(f"Operation failed after retries; context={debug}") from exc

        assert last_error is not None  # pragma: no cover - defensive
        raise last_error

    context: Dict[str, Any] = {
        "namespace": namespace,
        "retry": retry,
        "get_debug_context": lambda: _debug_context(namespace, attempts_observed, tuple(delays)),
        "cleanup_log": cleanup_log,
        "middleware_chain": ("RateLimit", "Idempotency", "Auth"),
    }

    try:
        yield context
    finally:
        cleanup_log.append(f"cleanup::{namespace}")
        _STATE_REGISTRY.discard(namespace)

