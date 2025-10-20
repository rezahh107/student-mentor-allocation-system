from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sma.phase6_import_to_sabt.app.timing import MonotonicTimer, Timer
from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics


@dataclass(slots=True)
class PerformanceHarness:
    metrics: ServiceMetrics
    timer: Timer = field(default_factory=MonotonicTimer)
    samples: list[float] = field(default_factory=list)

    async def run(self, operation: Callable[[], Awaitable[None]], *, iterations: int = 1) -> None:
        for _ in range(iterations):
            handle = self.timer.start()
            await operation()
            duration = handle.elapsed()
            self.samples.append(duration)
            self.metrics.request_latency.observe(duration)

    def record(self, duration: float) -> None:
        self.samples.append(duration)
        self.metrics.request_latency.observe(duration)

    def p95(self) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        index = max(int(round(0.95 * len(ordered) + 0.5)) - 1, 0)
        return ordered[index]

    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0.0

    def assert_within_budget(self, budget: float) -> None:
        actual = self.p95()
        assert actual <= budget, f"p95 {actual:.4f}s exceeds budget {budget:.4f}s"


__all__ = ["PerformanceHarness"]
