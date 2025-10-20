from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Protocol


class TimerHandle(Protocol):
    def elapsed(self) -> float:
        ...


class Timer(Protocol):
    def start(self) -> TimerHandle:
        ...


@dataclass(slots=True)
class _PerfHandle:
    started: float

    def elapsed(self) -> float:
        return time.perf_counter() - self.started


class MonotonicTimer:
    def start(self) -> TimerHandle:
        return _PerfHandle(time.perf_counter())


class DeterministicTimer:
    """Deterministic timer for tests using scripted durations."""

    def __init__(self, durations: list[float] | None = None) -> None:
        self._durations = itertools.cycle(durations or [0.0])
        self.recorded: list[float] = []

    def start(self) -> TimerHandle:
        next_duration = next(self._durations)

        class _Handle:
            def __init__(self, timer: DeterministicTimer, duration: float) -> None:
                self._timer = timer
                self._duration = duration

            def elapsed(self) -> float:
                self._timer.recorded.append(self._duration)
                return self._duration

        return _Handle(self, next_duration)


__all__ = ["Timer", "TimerHandle", "MonotonicTimer", "DeterministicTimer"]
