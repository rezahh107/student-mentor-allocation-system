from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from src.services import DEFAULT_CHUNK_SIZE, export_to_xlsx, stream_students
from tests.fixtures.perf import persist_budget_summary

if TYPE_CHECKING:  # pragma: no cover - typing aid only
    from .conftest import PerformanceMonitor


P95_BUDGET_SECONDS = 15.0
P99_BUDGET_SECONDS = 20.0
MEMORY_BUDGET_MB = 150.0


@dataclass(slots=True)
class ExportSampleStats:
    label: str
    samples: int
    p50: float
    p95: float
    p99: float
    peak_mb: float


@dataclass(frozen=True, slots=True)
class BudgetScenario:
    label: str
    runs: int
    expected_rows: int
    chunk_size: int = DEFAULT_CHUNK_SIZE


def _rows_factory(total: int) -> Callable[[], Iterable[dict[str, str]]]:
    def _builder() -> Iterable[dict[str, str]]:
        for index in range(total):
            base = f"{index:010d}"
            yield {
                "national_id": base,
                "counter": f"{index:09d}",
                "first_name": f"دانش‌آموز-{index}",
                "last_name": f"نمونه-{index}",
                "gender": "1",
                "mobile": f"0912{index:06d}",
                "reg_center": f"{(index // 1000) % 5}",
                "reg_status": "3",
                "group_code": f"{index % 97:02d}",
                "student_type": "1",
                "school_code": f"{(index % 10_000):06d}",
                "mentor_id": f"{index:08d}",
                "mentor_name": f"راهنما-{index}",
                "mentor_mobile": f"0999{index:06d}",
                "allocation_date": "1403-01-01",
                "year_code": "1403",
            }

    return _builder


def _measure_export(
    *,
    monitor: PerformanceMonitor,
    rows_factory: Callable[[], Iterable[dict[str, str]]],
    tmp_path: Path,
    scenario: BudgetScenario,
) -> ExportSampleStats:
    actual_total = scenario.expected_rows

    def _operation() -> None:
        target_dir = tmp_path / f"export-{uuid4().hex}"
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            manifest = export_to_xlsx(
                students=stream_students(rows_factory()),
                output_path=target_dir / "export.xlsx",
                chunk_size=scenario.chunk_size,
                clock=monitor.clock,
            )
            assert manifest.row_count == actual_total, (
                "تعداد ردیف‌های تولید‌شده کمتر از مقدار انتظار است",
                monitor.debug(scenario.label),
            )
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)

    for _ in range(scenario.runs):
        monitor.run_with_retry(scenario.label, _operation)

    p50 = monitor.percentile(scenario.label, 50)
    p95 = monitor.percentile(scenario.label, 95)
    p99 = monitor.percentile(scenario.label, 99)
    peak_mb = monitor.peak_memory(scenario.label) / (1024 * 1024)
    return ExportSampleStats(
        label=scenario.label,
        samples=scenario.runs,
        p50=p50,
        p95=p95,
        p99=p99,
        peak_mb=peak_mb,
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_export_xlsx_100k_budget(
    performance_monitor: PerformanceMonitor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the XLSX exporter satisfies the AGENTS §8.1 budgets for 100k rows."""

    monkeypatch.setenv("SMA_PERF_FAST", "0")
    total_rows = int(os.getenv("SMA_PERF_SAMPLE_SIZE", "100000"))
    rows = _rows_factory(total_rows)
    stats = _measure_export(
        monitor=performance_monitor,
        rows_factory=rows,
        tmp_path=tmp_path,
        scenario=BudgetScenario(
            label="export_100k_budget",
            runs=1,
            expected_rows=total_rows,
        ),
    )
    context = performance_monitor.debug(stats.label)
    assert stats.p95 <= P95_BUDGET_SECONDS, (
        "p95 فرایند تولید خروجی اکسل از بودجهٔ ۱۵ ثانیه فراتر رفت",
        context,
    )
    assert stats.p99 <= P99_BUDGET_SECONDS, (
        "p99 فرایند تولید خروجی اکسل از بودجهٔ ۲۰ ثانیه بیشتر است",
        context,
    )
    assert stats.peak_mb <= MEMORY_BUDGET_MB, (
        "مصرف حافظهٔ تولید خروجی اکسل بیش از بودجهٔ ۱۵۰ مگابایت است",
        context,
    )
    assert stats.p50 <= stats.p95 <= stats.p99, context

    summary = {
        "label": stats.label,
        "p95_seconds": stats.p95,
        "p99_seconds": stats.p99,
        "peak_memory_mb": stats.peak_mb,
        "samples": stats.samples,
    }
    persist_budget_summary(summary)
    performance_monitor.persist()
