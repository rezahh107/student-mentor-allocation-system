"""Retry backoff determinism tests citing AGENTS.md::Determinism."""

from __future__ import annotations

import uuid

import pytest

from src.ops.retry import build_retry_metrics, execute_with_retry
from tests.conftest import DeterministicClock
from tests.fixtures.retry import DeterministicBackoffPolicy

_ANCHOR = "AGENTS.md::Determinism"


def _policy_sequence(policy: DeterministicBackoffPolicy, attempts: int) -> list[float]:
    return [policy.compute(i) for i in range(1, attempts + 1)]


def test_backoff_is_deterministic_per_namespace(clock: DeterministicClock) -> None:
    namespace = f"retry-{uuid.uuid4().hex}"
    base_policy = DeterministicBackoffPolicy(operation="phase6.retry", namespace=namespace, route="/ops")
    first = _policy_sequence(base_policy, 5)
    again = _policy_sequence(
        DeterministicBackoffPolicy(operation="phase6.retry", namespace=namespace, route="/ops"),
        5,
    )
    assert first == again, {"anchor": _ANCHOR, "sequence": first}


def test_backoff_differs_for_distinct_namespace(clock: DeterministicClock) -> None:
    policy_a = DeterministicBackoffPolicy(operation="phase6.retry", namespace="ns-a", route="/alloc")
    policy_b = DeterministicBackoffPolicy(operation="phase6.retry", namespace="ns-b", route="/alloc")
    assert _policy_sequence(policy_a, 4) != _policy_sequence(policy_b, 4), {
        "anchor": _ANCHOR,
        "a": _policy_sequence(policy_a, 4),
        "b": _policy_sequence(policy_b, 4),
    }


def test_attempt_and_exhaustion_counters(clock: DeterministicClock) -> None:
    namespace = f"retry-metrics-{uuid.uuid4().hex}"
    metrics = build_retry_metrics(namespace)
    policy = DeterministicBackoffPolicy(operation="ops.retry", namespace=namespace, route="/task")
    attempts: dict[str, int] = {"count": 0}

    def _success_after_two() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("unstable")
        return "ok"

    result = execute_with_retry(
        _success_after_two,
        policy=policy.compute,
        max_attempts=3,
        metrics=metrics,
        clock_tick=lambda seconds: clock.tick(seconds=seconds),
        operation_name="ops.retry",
    )
    assert result == "ok", {"anchor": _ANCHOR, "attempts": attempts["count"]}
    success_value = metrics.registry.get_sample_value(
        f"{namespace}_retry_attempts_total",
        {"operation": "ops.retry", "namespace": namespace, "outcome": "success"},
    )
    assert success_value == pytest.approx(3.0), {
        "anchor": _ANCHOR,
        "success_value": success_value,
    }

    attempts["count"] = 0

    def _always_fail() -> str:
        attempts["count"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        execute_with_retry(
            _always_fail,
            policy=policy.compute,
            max_attempts=2,
            metrics=metrics,
            clock_tick=lambda seconds: clock.tick(seconds=seconds),
            operation_name="ops.retry",
        )

    failure_value = metrics.registry.get_sample_value(
        f"{namespace}_retry_attempts_total",
        {"operation": "ops.retry", "namespace": namespace, "outcome": "error"},
    )
    exhaustion = metrics.registry.get_sample_value(
        f"{namespace}_retry_exhaustion_total",
        {"operation": "ops.retry", "namespace": namespace},
    )
    histogram_bucket = metrics.registry.get_sample_value(
        f"{namespace}_retry_backoff_seconds_bucket",
        {"operation": "ops.retry", "namespace": namespace, "le": "0.2"},
    )
    assert failure_value == pytest.approx(2.0), {
        "anchor": _ANCHOR,
        "failure_value": failure_value,
    }
    assert exhaustion == pytest.approx(1.0), {"anchor": _ANCHOR, "exhaustion": exhaustion}
    assert histogram_bucket is not None, {
        "anchor": _ANCHOR,
        "bucket": histogram_bucket,
    }
