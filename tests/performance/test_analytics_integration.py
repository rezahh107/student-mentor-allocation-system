import asyncio
import time

import pytest

from sma.core.models import Mentor, Student
from sma.ui.services.config_manager import ConfigManager
from sma.ui.services.performance_monitor import PerformanceMonitor
from sma.ui.services.allocation_backend import MockBackendService

try:
    from sma.ui.pages.allocation_presenter import AllocationPresenter
except RuntimeError as exc:  # pragma: no cover - headless environments
    pytest.skip(
        f"GUI_HEADLESS_SKIPPED: محیط گرافیکی برای تست آنالیز در دسترس نیست ({exc})",
        allow_module_level=True,
    )


@pytest.mark.asyncio
async def test_large_scale_allocation_performance():
    backend = MockBackendService(student_count=0, mentor_count=0)

    student_count = 5000
    backend.students = [
        Student(
            id=index,
            gender=index % 2,
            grade_level=10 + (index % 3),
            center_id=1 + (index % 5),
            name=f"Student {index}",
        )
        for index in range(student_count)
    ]

    backend.mentors = [
        Mentor(
            id=index + 1,
            gender=index % 2,
            supported_grades=[10, 11, 12],
            max_capacity=60,
            current_students=0,
            center_id=1 + (index % 5),
            name=f"Mentor {index + 1}",
        )
        for index in range(120)
    ]

    presenter = AllocationPresenter(backend)

    start = time.perf_counter()
    results = await presenter.run_allocation(
        same_center_only=False,
        prefer_lower_load=True,
        capacity_weight=20,
    )
    duration = time.perf_counter() - start

    assert duration < 15
    assert results["successful"] > 0
    assert results["successful"] + results["failed"] == student_count


def test_performance_monitor_metrics():
    monitor = PerformanceMonitor(history_size=5)
    monitor.start_monitoring()
    time.sleep(1.5)
    monitor.stop_monitoring()

    monitor.record_allocation_performance(duration=2.0, student_count=200, success_count=150)

    metrics = monitor.get_current_metrics()
    summary = monitor.get_performance_summary()

    assert "cpu" in metrics and "memory" in metrics
    assert summary["total_allocations"] >= 1
    assert summary["avg_throughput"] > 0


def test_config_manager_persistence(tmp_path):
    config_file = tmp_path / "test_allocation_config.json"

    manager = ConfigManager(config_file=config_file)
    manager.update_config(
        same_center_only=False,
        prefer_lower_load=False,
        capacity_weight=1.5,
    )

    reloaded = ConfigManager(config_file=config_file)
    assert not reloaded.config.same_center_only
    assert not reloaded.config.prefer_lower_load
    assert pytest.approx(reloaded.config.capacity_weight, rel=1e-3) == 1.5

