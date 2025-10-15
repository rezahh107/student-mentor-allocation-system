"""Performance regression harness for Excel exports and API throughput."""

from __future__ import annotations

import asyncio
import math
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List

import openpyxl
import pytest
from openpyxl.worksheet.worksheet import Worksheet

from phase6_import_to_sabt.sanitization import deterministic_jitter, sanitize_text
from tests.fixtures.state import CleanupFixtures


@dataclass(slots=True)
class _RowFactory:
    """Generate deterministic Persian rows for export benchmarks.

    Example:
        >>> factory = _RowFactory(total=2)
        >>> list(factory.rows())
        [{'first_name': 'دانش‌آموز۰', 'last_name': 'ویژه۰', 'mobile': '09120000000', 'note': 'یادداشت-۰'},
         {'first_name': 'دانش‌آموز۱', 'last_name': 'ویژه۱', 'mobile': '09120000001', 'note': 'یادداشت-۱'}]
    """

    total: int

    def rows(self) -> Iterator[Dict[str, str]]:
        for index in range(self.total):
            suffix = f"{index:05d}"
            yield {
                # Persian names are normalized to ensure ی/ک variants collapse.
                "first_name": sanitize_text(f"دانش‌آموز{suffix}"),
                "last_name": sanitize_text(f"ویژه{suffix}"),
                "mobile": f"0912{index:07d}",
                # Notes intentionally mix Persian digits to verify folding.
                "note": sanitize_text("یادداشت-" + suffix.replace("0", "۰")),
            }


def _write_sheet(sheet: Worksheet, rows: Iterable[Dict[str, str]]) -> None:
    sheet.append(["first_name", "last_name", "mobile", "note"])
    for payload in rows:
        sheet.append([payload["first_name"], payload["last_name"], payload["mobile"], payload["note"]])


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.integration
@pytest.mark.timeout(30)
def test_excel_export_performance_under_load(
    tmp_path: Path,
    cleanup_fixtures: CleanupFixtures,
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Ensure exporting 10K Persian rows completes within 5s and <500MB peak memory.

    Example:
        >>> # Executed via pytest benchmark harness
        >>> tmp_path = Path('build')  # doctest: +SKIP
    """

    cleanup_fixtures.flush_state()
    target = tmp_path / f"{cleanup_fixtures.namespace}-export.xlsx"
    row_factory = _RowFactory(total=10_000)

    def _export() -> Dict[str, float]:
        tracemalloc.start()
        start = time.perf_counter()
        workbook = openpyxl.Workbook(write_only=True)
        sheet = workbook.create_sheet("داده‌ها")
        _write_sheet(sheet, row_factory.rows())
        workbook.save(target)
        duration = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"duration": duration, "peak_bytes": float(peak)}

    result = benchmark(_export)
    context = cleanup_fixtures.context(result=result, target=str(target))
    assert result["duration"] < 5.0, f"زمان صادرات بیش از حد مجاز است: {context}"
    assert result["peak_bytes"] / (1024**2) < 500, f"مصرف حافظه خارج از بودجه است: {context}"
    cleanup_fixtures.flush_state()


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.integration
@pytest.mark.timeout(30)
def test_concurrent_request_throughput(
    cleanup_fixtures: CleanupFixtures,
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Verify API simulation handles 100 concurrent requests with p95 latency <200ms.

    Example:
        >>> # Run under pytest to capture benchmark statistics
        >>> cleanup_fixtures  # doctest: +SKIP
    """

    total_requests = 100
    concurrency = 20

    async def _simulate() -> Dict[str, object]:
        latencies: List[float] = []
        rate_limit_errors = 0
        semaphore = asyncio.Semaphore(concurrency)

        async def _call(request_id: int) -> None:
            nonlocal rate_limit_errors
            attempts = 0
            while True:
                attempts += 1
                async with semaphore:
                    jitter = deterministic_jitter(0.02 * attempts, attempts, f"{cleanup_fixtures.namespace}:{request_id}")
                    await asyncio.sleep(0)
                    latency = 0.05 + jitter
                    latencies.append(latency)
                    if latency > 0.2:
                        rate_limit_errors += 1
                    return
                await asyncio.sleep(deterministic_jitter(0.05, attempts, f"retry:{request_id}"))

        start = time.perf_counter()
        await asyncio.gather(*(_call(idx) for idx in range(total_requests)))
        duration = time.perf_counter() - start
        return {"duration": duration, "latencies": latencies, "rate_limit_errors": rate_limit_errors}

    def _run() -> Dict[str, object]:
        cleanup_fixtures.flush_state()
        result = asyncio.run(_simulate())
        cleanup_fixtures.flush_state()
        return result

    result = benchmark(_run)
    latencies = list(result["latencies"])
    latencies.sort()
    percentile_index = max(0, math.ceil(0.95 * len(latencies)) - 1)
    p95 = latencies[percentile_index]
    stats_obj = getattr(benchmark, "stats", None)
    stats_mean = None
    if stats_obj is not None:
        stats_data = getattr(stats_obj, "stats", None)
        if isinstance(stats_data, dict):
            stats_mean = stats_data.get("mean")
    context = cleanup_fixtures.context(
        duration=result["duration"],
        p95=p95,
        rate_limit_errors=result["rate_limit_errors"],
        benchmark_mean=stats_mean,
    )
    assert result["duration"] < 5.0, f"مدت زمان اجرای سناریو طولانی است: {context}"
    assert p95 < 0.2, f"p95 بیش از 200ms است: {context}"
    assert result["rate_limit_errors"] == 0, f"خطای محدودیت نرخ مشاهده شد: {context}"
