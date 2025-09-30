"""Deterministic retry tooling honoring AGENTS.md::Determinism."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol, TypeVar

import pytest

from tests.conftest import DeterministicClock

_ANCHOR = "AGENTS.md::Determinism"
_MIN_DELAY = 0.0


class Operation(Protocol):
    def __call__(self) -> object:  # pragma: no cover - protocol signature
        ...


T = TypeVar("T")


@dataclass(slots=True)
class DeterministicBackoffPolicy:
    """Compute deterministic BLAKE2 jitter for retries."""

    operation: str
    namespace: str
    route: str = ""
    base_delay: float = 0.05
    multiplier: float = 2.0

    def compute(self, attempt: int) -> float:
        seed_base = f"{self.namespace}:{self.operation}:{self.route}".encode("utf-8")
        seed = seed_base + f":{attempt}".encode("utf-8")
        digest = hashlib.blake2s(seed, digest_size=8).digest()
        jitter = int.from_bytes(digest, "big") / float(1 << 64)
        factor = 0.5 + jitter  # ensures deterministic but bounded scaling
        delay = self.base_delay * (self.multiplier ** max(attempt - 1, 0)) * factor
        return max(_MIN_DELAY, round(delay, 6))


def execute_with_policy(
    operation: Callable[[], T],
    *,
    policy: DeterministicBackoffPolicy,
    clock: DeterministicClock,
    max_attempts: int,
) -> T:
    attempts = 0
    last_error: Exception | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - exercised in tests
            last_error = exc
            if attempts >= max_attempts:
                break
            delay = policy.compute(attempts)
            clock.tick(seconds=delay)
    assert last_error is not None, {"anchor": _ANCHOR, "reason": "missing error"}
    raise last_error


@pytest.fixture()
def retry_policy(clock: DeterministicClock) -> Iterator[DeterministicBackoffPolicy]:
    policy = DeterministicBackoffPolicy(operation="test.op", namespace=clock.now().isoformat())
    yield policy


__all__ = ["DeterministicBackoffPolicy", "execute_with_policy", "retry_policy"]
