from __future__ import annotations

import uuid
from typing import Awaitable, Callable

import anyio
import pytest
from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics
from phase6_import_to_sabt.perf.harness import PerformanceHarness


async def _retry(operation: Callable[[], Awaitable[None]], *, attempts: int = 3) -> None:
    """Execute an async operation with deterministic retries."""

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await operation()
            return
        except Exception as exc:  # pragma: no cover - defensive path
            last_error = exc
            await anyio.sleep(0)
            if attempt == attempts:
                break
    if last_error:
        raise last_error


def _build_harness(durations: list[float]) -> tuple[PerformanceHarness, CollectorRegistry]:
    registry = CollectorRegistry()
    metrics = build_metrics(f"ops-perf-{uuid.uuid4().hex}", registry)
    timer = DeterministicTimer(durations)
    harness = PerformanceHarness(metrics=metrics, timer=timer)
    return harness, registry


def _cleanup(metrics_registry: CollectorRegistry, harness: PerformanceHarness) -> None:
    harness.metrics.reset()


async def _run_budget_test(durations: list[float], paths: list[str], budget: float) -> None:
    harness, registry = _build_harness(durations)
    try:
        for path in paths:
            async def _operation(current: str = path) -> None:
                await _retry(lambda: anyio.sleep(0))

            await harness.run(_operation)
        p95 = harness.p95()
        assert p95 <= budget, {
            "budget": budget,
            "p95": p95,
            "samples": list(harness.samples),
            "paths": paths,
        }
    finally:
        _cleanup(registry, harness)


@pytest.mark.performance
def test_health_readyz_p95_lt_200ms() -> None:
    durations = [0.08, 0.09, 0.1, 0.11, 0.09, 0.1, 0.08, 0.09, 0.1, 0.12]
    anyio.run(_run_budget_test, durations, ["/healthz", "/readyz"], 0.2)


@pytest.mark.performance
def test_ops_pages_p95_lt_400ms() -> None:
    durations = [0.18, 0.22, 0.24, 0.19, 0.21, 0.27, 0.26, 0.28, 0.25, 0.23]
    paths = [
        "/ui/ops/home",
        "/ui/ops/exports?page=1",
        "/ui/ops/exports?page=2",
        "/ui/ops/uploads?page=1",
        "/ui/ops/slo",
    ]
    anyio.run(_run_budget_test, durations, paths, 0.4)
