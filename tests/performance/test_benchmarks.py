from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sma.phase6_import_to_sabt.export_writer import ExportWriter

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from .conftest import PerformanceMonitor


DATASET_ROWS = 4096


def _percentile(data: list[float], percentile: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    rank = max(0, math.ceil((percentile / 100.0) * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


@pytest.mark.benchmark
@pytest.mark.performance
def test_excel_writer_benchmark(performance_monitor: "PerformanceMonitor", benchmark, tmp_path: Path) -> None:
    writer = ExportWriter(sensitive_columns=("national_id", "counter", "mobile"), chunk_size=16000)
    rows = [
        {
            "national_id": f"{index:010d}",
            "counter": f"373{index:07d}",
            "first_name": "نام",
            "last_name": "کاربر",
            "gender": "1",
            "mobile": "09120000000",
            "reg_center": "1",
            "reg_status": "3",
            "group_code": "42",
            "student_type": "special",
            "school_code": "1000",
            "mentor_id": f"{index:08d}",
            "mentor_name": "مربی",
            "mentor_mobile": "09123334444",
            "allocation_date": "1403-01-01",
            "year_code": "1403",
        }
        for index in range(DATASET_ROWS)
    ]

    def _operation() -> None:
        target = tmp_path / f"bench-{uuid4().hex}"
        target.mkdir(parents=True, exist_ok=True)
        try:
            performance_monitor.run_with_retry(
                "excel_benchmark",
                lambda: writer.write_xlsx(rows, path_factory=lambda idx: target / f"export-{idx}.xlsx"),
            )
        finally:
            for file in target.glob("*.xlsx"):
                file.unlink(missing_ok=True)
            target.rmdir()

    stats = benchmark.pedantic(_operation, iterations=1, rounds=5)
    samples = list(stats.stats.get("data", []))
    assert samples, "pytest-benchmark داده‌ای ثبت نکرد"
    p95 = _percentile(samples, 95)
    assert p95 <= 2.0, (
        "p95 تولید اکسل از مرز ۲ ثانیه عبور کرده است",
        performance_monitor.debug("excel_benchmark"),
    )


@pytest.mark.benchmark
@pytest.mark.performance
def test_retry_window_benchmark(performance_monitor: "PerformanceMonitor", benchmark) -> None:
    def _operation() -> None:
        counter = {"value": 0}

        def _task() -> None:
            counter["value"] += 1
            if counter["value"] == 1:
                raise RuntimeError("transient-error")

        performance_monitor.run_with_retry("retry_window", _task, retryable=(RuntimeError,))

    stats = benchmark.pedantic(_operation, iterations=1, rounds=6)
    samples = list(stats.stats.get("data", []))
    assert samples, "pytest-benchmark داده‌ای ثبت نکرد"
    p95 = _percentile(samples, 95)
    assert p95 <= 0.5, (
        "پنجرهٔ تلاش مجدد بیش از بودجهٔ ۵۰۰ میلی‌ثانیه طول کشید",
        performance_monitor.debug("retry_window"),
    )


@pytest.mark.benchmark
@pytest.mark.performance
def test_memory_pressure_benchmark(performance_monitor: "PerformanceMonitor", benchmark) -> None:
    payload = bytes(range(256)) * 1024

    def _operation() -> None:
        def _task() -> None:
            buffer = bytearray()
            buffer.extend(payload)
            buffer.clear()

        performance_monitor.run_with_retry("memory_benchmark", _task)

    stats = benchmark.pedantic(_operation, iterations=3, rounds=5)
    samples = list(stats.stats.get("data", []))
    assert samples, "pytest-benchmark داده‌ای ثبت نکرد"
    p95 = _percentile(samples, 95)
    assert p95 <= 0.1, (
        "پاکسازی حافظه کندتر از بودجهٔ ۱۰۰ میلی‌ثانیه بود",
        performance_monitor.debug("memory_benchmark"),
    )
    assert performance_monitor.peak_memory("memory_benchmark") <= 32 * 1024 * 1024, (
        "افزایش حافظه بیش از سقف ۳۲MB گزارش شد",
        performance_monitor.debug("memory_benchmark"),
    )
