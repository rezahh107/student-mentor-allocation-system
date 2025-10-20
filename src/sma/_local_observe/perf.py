"""Performance telemetry utilities for phase 3 allocation tools."""
from __future__ import annotations

import json
import math
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence


@dataclass(frozen=True)
class PerfStats:
    """Aggregated statistics for a label."""

    count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    memory_peak_bytes: int


class PerformanceObserver:
    """Collect duration, memory peaks, and counters with Bandit-safe APIs."""

    def __init__(self) -> None:
        self._samples: Dict[str, List[float]] = {}
        self._memory_peaks: Dict[str, List[int]] = {}
        self._counters: Dict[str, int] = {}
        if not tracemalloc.is_tracing():
            tracemalloc.start()

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        """Measure latency and memory for the provided label."""

        start_time = time.perf_counter()
        _, before_peak = tracemalloc.get_traced_memory()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            _, after_peak = tracemalloc.get_traced_memory()
            peak_bytes = max(0, after_peak - before_peak)
            self._samples.setdefault(label, []).append(duration_ms)
            self._memory_peaks.setdefault(label, []).append(peak_bytes)

    def increment_counter(self, name: str, *, amount: int = 1) -> None:
        """Increase a named counter."""

        self._counters[name] = self._counters.get(name, 0) + amount

    def counters_snapshot(self) -> Dict[str, int]:
        """Return a copy of all counters."""

        return dict(self._counters)

    def stats(self, label: str) -> PerfStats | None:
        """Return aggregated statistics for a label if available."""

        durations = self._samples.get(label)
        if not durations:
            return None
        memory_peaks = self._memory_peaks.get(label, [0])
        return PerfStats(
            count=len(durations),
            p50_ms=_percentile(durations, 50.0),
            p95_ms=_percentile(durations, 95.0),
            max_ms=max(durations),
            memory_peak_bytes=max(memory_peaks) if memory_peaks else 0,
        )

    def stats_snapshot(self) -> Dict[str, PerfStats]:
        """Return statistics for all recorded labels."""

        snapshot: Dict[str, PerfStats] = {}
        for label in self._samples:
            stats = self.stats(label)
            if stats is not None:
                snapshot[label] = stats
        return snapshot

    def summary(self) -> "PerfSummary":
        """Return a serialisable summary of samples, peaks, and counters."""

        durations = {label: list(values) for label, values in self._samples.items()}
        memory = {label: list(values) for label, values in self._memory_peaks.items()}
        counters = dict(self._counters)
        return PerfSummary(durations=durations, memory=memory, counters=counters)

    def to_json(self, path: str | Path) -> None:
        """Persist telemetry summary to a JSON file."""

        self.summary().to_json(path)

    @staticmethod
    def merge(summaries: Sequence["PerfSummary"]) -> "PerfSummary":
        """Merge multiple summaries into a single aggregate summary."""

        if not summaries:
            return PerfSummary(durations={}, memory={}, counters={})
        merged = summaries[0]
        for summary in summaries[1:]:
            merged = merged.merge(summary)
        return merged


def _percentile(values: Iterable[float], percentile: float) -> float:
    data = list(values)
    if not data:
        raise ValueError("هیچ نمونه‌ای برای محاسبه صدک وجود ندارد.")
    if len(data) == 1:
        return data[0]
    ordered = sorted(data)
    if percentile <= 0:
        return ordered[0]
    if percentile >= 100:
        return ordered[-1]
    rank = (len(ordered) - 1) * (percentile / 100.0)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return ordered[lower_index]
    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    fraction = rank - lower_index
    return lower_value + (upper_value - lower_value) * fraction


@dataclass(frozen=True)
class PerfSummary:
    """Serializable telemetry summary with helper utilities."""

    durations: Dict[str, List[float]]
    memory: Dict[str, List[int]]
    counters: Dict[str, int]

    def stats(self) -> Dict[str, PerfStats]:
        """Return percentile statistics derived from captured samples."""

        stats: Dict[str, PerfStats] = {}
        for label, samples in self.durations.items():
            peaks = self.memory.get(label, [0])
            stats[label] = PerfStats(
                count=len(samples),
                p50_ms=_percentile(samples, 50.0),
                p95_ms=_percentile(samples, 95.0),
                max_ms=max(samples) if samples else 0.0,
                memory_peak_bytes=max(peaks) if peaks else 0,
            )
        return stats

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable mapping with percentile summaries."""

        stats = self.stats()
        return {
            "durations": self.durations,
            "memory": self.memory,
            "p50": {label: value.p50_ms for label, value in stats.items()},
            "p95": {label: value.p95_ms for label, value in stats.items()},
            "max": {label: value.max_ms for label, value in stats.items()},
            "mem_peak": {
                label: value.memory_peak_bytes for label, value in stats.items()
            },
            "counters": self.counters,
        }

    def to_json(self, path: str | Path) -> None:
        """Persist the summary to JSON, ensuring UTF-8 output."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)

    def merge(self, other: "PerfSummary") -> "PerfSummary":
        """Combine two summaries, concatenating samples and counters."""

        durations: Dict[str, List[float]] = {
            label: list(values) for label, values in self.durations.items()
        }
        for label, samples in other.durations.items():
            durations.setdefault(label, []).extend(samples)
        memory: Dict[str, List[int]] = {
            label: list(values) for label, values in self.memory.items()
        }
        for label, peaks in other.memory.items():
            memory.setdefault(label, []).extend(peaks)
        counters = dict(self.counters)
        for name, value in other.counters.items():
            counters[name] = counters.get(name, 0) + value
        return PerfSummary(durations=durations, memory=memory, counters=counters)

    @classmethod
    def from_json(cls, path: str | Path) -> "PerfSummary":
        """Load a summary from a JSON file."""

        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        durations = {
            label: [float(value) for value in values]
            for label, values in payload.get("durations", {}).items()
        }
        memory = {
            label: [int(value) for value in values]
            for label, values in payload.get("memory", {}).items()
        }
        counters = {
            name: int(value) for name, value in payload.get("counters", {}).items()
        }
        return cls(durations=durations, memory=memory, counters=counters)


__all__ = ["PerformanceObserver", "PerfStats", "PerfSummary"]

