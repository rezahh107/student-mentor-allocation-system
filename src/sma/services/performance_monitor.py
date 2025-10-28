from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, Dict

import psutil

from sma.core.clock import Clock, ensure_clock


class PerformanceMonitor:
    """مانیتورینگ ساده برای ثبت سرعت تخصیص و وضعیت سیستم."""

    def __init__(self, *, clock: Clock | None = None, history_size: int = 10) -> None:
        self._clock = ensure_clock(clock, default=Clock.for_tehran())
        self.start_time = self._clock.unix_timestamp()
        self._timezone = self._clock.timezone
        self._allocation_count = 0
        self._durations: list[float] = []
        self._successful_students = 0
        self._total_students = 0
        self._last_update: datetime | None = None
        self._history: Deque[Dict[str, object]] = deque(maxlen=max(1, int(history_size)))
        self._monitoring_active = False
        self._monitoring_started_at: float | None = None

    def start_monitoring(self) -> None:
        if self._monitoring_active:
            return
        self._monitoring_active = True
        self._monitoring_started_at = self._clock.unix_timestamp()

    def stop_monitoring(self) -> None:
        if not self._monitoring_active:
            return
        elapsed = self._clock.unix_timestamp() - (self._monitoring_started_at or self.start_time)
        self._history.append({"label": "monitoring_window", "duration": max(0.0, float(elapsed))})
        self._monitoring_active = False
        self._monitoring_started_at = None

    def record_allocation_performance(
        self,
        *,
        duration: float,
        student_count: int = 0,
        success_count: int = 0,
    ) -> None:
        self._allocation_count += 1
        self._durations.append(max(0.0, float(duration)))
        self._successful_students += max(0, int(success_count))
        self._total_students += max(0, int(student_count))
        self._last_update = self._clock.now()
        self._history.append(
            {
                "label": "allocation",
                "duration": max(0.0, float(duration)),
                "students": max(0, int(student_count)),
                "success": max(0, int(success_count)),
            }
        )

    def get_current_metrics(self) -> Dict[str, object]:
        try:
            memory = psutil.virtual_memory().percent
        except Exception:  # pragma: no cover - defensive on limited platforms
            memory = 0.0
        try:
            cpu = psutil.cpu_percent(interval=None)
        except Exception:  # pragma: no cover - defensive fallback
            cpu = 0.0
        uptime = int(self._clock.unix_timestamp() - self.start_time)
        return {
            "cpu": round(float(cpu), 2),
            "memory": round(float(memory), 2),
            "uptime_seconds": uptime,
        }

    def get_performance_summary(self) -> Dict[str, object]:
        avg_time = sum(self._durations) / len(self._durations) if self._durations else 0.0
        throughput = (
            (self._successful_students / avg_time) if avg_time > 0 else 0.0
        )
        return {
            "total_allocations": self._allocation_count,
            "avg_time": round(avg_time, 3),
            "avg_throughput": round(throughput, 3),
            "history": list(self._history),
        }

    def record_allocation(
        self,
        duration: float,
        *,
        total_students: int = 0,
        successful_students: int = 0,
    ) -> None:
        """Backward compatible wrapper for legacy callers."""

        self.record_allocation_performance(
            duration=max(0.0, float(duration)),
            student_count=total_students,
            success_count=successful_students,
        )

    def get_stats(self) -> Dict[str, object]:
        summary = self.get_performance_summary()
        metrics = self.get_current_metrics()
        success_rate = (
            (self._successful_students / self._total_students) * 100.0
            if self._total_students
            else 0.0
        )
        return {
            "total_allocations": summary["total_allocations"],
            "average_time": summary["avg_time"],
            "memory_usage": metrics["memory"],
            "uptime_seconds": metrics["uptime_seconds"],
            "success_rate": round(success_rate, 1),
            "last_update": self._last_update.astimezone(self._timezone).strftime("%H:%M:%S")
            if self._last_update
            else "---",
        }


__all__ = ["PerformanceMonitor"]
