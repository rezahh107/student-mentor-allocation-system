"""Deterministic retry tooling honoring AGENTS.md::Determinism."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterator, Protocol, TypeVar

import pytest

from tests.conftest import DeterministicClock
from phase6_import_to_sabt.observability import MetricsCollector

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


@dataclass(slots=True)
class CircuitBreakerState:
    failure_threshold: int = 3
    reset_timeout: float = 1.5
    _failures: int = 0
    _open_until: float = 0.0

    def allow(self, clock: DeterministicClock) -> bool:
        return clock.now().timestamp() >= self._open_until

    def record_failure(self, *, clock: DeterministicClock, penalty: float) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = clock.now().timestamp() + self.reset_timeout + penalty
            self._failures = 0

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0


@dataclass(slots=True)
class RetryTelemetry:
    attempts: int = 0
    failures: int = 0
    delays: list[float] = field(default_factory=list)
    last_error: Exception | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "failures": self.failures,
            "delays": list(self.delays),
            "last_error": None if self.last_error is None else type(self.last_error).__name__,
        }


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


@pytest.fixture()
def retry_harness(
    clock: DeterministicClock,
) -> Iterator[tuple[Callable[[Callable[[], T]], tuple[T, RetryTelemetry, MetricsCollector]], MetricsCollector]]:
    policy = DeterministicBackoffPolicy(operation="test.op", namespace=clock.now().isoformat())
    breaker = CircuitBreakerState()
    collector = MetricsCollector()

    def _run(
        operation: Callable[[], T],
        *,
        max_attempts: int = 3,
        failure_threshold: int | None = None,
    ) -> tuple[T, RetryTelemetry, MetricsCollector]:
        telemetry = RetryTelemetry()
        original_threshold = breaker.failure_threshold
        if failure_threshold is not None:
            breaker.failure_threshold = failure_threshold
        while telemetry.attempts < max_attempts:
            if not breaker.allow(clock):
                telemetry.last_error = RuntimeError("circuit-open")
                collector.record_retry_attempt(outcome="open")
                break
            telemetry.attempts += 1
            try:
                result = operation()
            except Exception as exc:  # pragma: no cover - exercised in tests
                telemetry.failures += 1
                telemetry.last_error = exc
                collector.record_retry_attempt(outcome="failure")
                delay = policy.compute(telemetry.attempts)
                telemetry.delays.append(delay)
                clock.tick(seconds=delay)
                breaker.record_failure(clock=clock, penalty=delay)
            else:
                collector.record_retry_attempt(outcome="success")
                breaker.record_success()
                breaker.failure_threshold = original_threshold
                return result, telemetry, collector
        breaker.failure_threshold = original_threshold
        assert telemetry.last_error is not None, {"anchor": _ANCHOR, "reason": "retry.exhausted"}
        collector.record_retry_attempt(outcome="exhausted")
        raise telemetry.last_error

    yield _run, collector


__all__ = [
    "CircuitBreakerState",
    "DeterministicBackoffPolicy",
    "RetryTelemetry",
    "execute_with_policy",
    "retry_policy",
    "retry_harness",
]
