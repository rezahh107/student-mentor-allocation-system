from __future__ import annotations

from datetime import datetime
from typing import Dict

import psutil

from sma.core.clock import Clock, ensure_clock

class PerformanceMonitor:
    """مانیتورینگ ساده برای ثبت سرعت تخصیص و وضعیت سیستم."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = ensure_clock(clock, default=Clock.for_tehran())
        self.start_time = self._clock.unix_timestamp()
        self._allocation_count = 0
        self._allocation_times: list[float] = []
        self._successful_students = 0
        self._total_students = 0
        self._last_update: datetime | None = None
        self._timezone = self._clock.timezone

    def record_allocation(self, duration: float, *, total_students: int = 0, successful_students: int = 0) -> None:
        self._allocation_count += 1
        self._allocation_times.append(duration)
        if len(self._allocation_times) > 100:
            self._allocation_times.pop(0)
        self._total_students += total_students
        self._successful_students += successful_students
        self._last_update = self._clock.now()

    def get_stats(self) -> Dict[str, object]:
        avg_time = sum(self._allocation_times) / len(self._allocation_times) if self._allocation_times else 0.0
        memory = psutil.virtual_memory().percent if psutil.virtual_memory else 0.0
        uptime = int(self._clock.unix_timestamp() - self.start_time)
        success_rate = (
            (self._successful_students / self._total_students) * 100.0
            if self._total_students
            else 0.0
        )
        return {
            "total_allocations": self._allocation_count,
            "average_time": round(avg_time, 3),
            "memory_usage": round(memory, 1),
            "uptime_seconds": uptime,
            "success_rate": round(success_rate, 1),
            "last_update": self._last_update.astimezone(self._timezone).strftime("%H:%M:%S")
            if self._last_update
            else "---",
        }


__all__ = ["PerformanceMonitor"]
