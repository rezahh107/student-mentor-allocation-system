from __future__ import annotations

import io
import shutil
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sma.phase6_import_to_sabt.export_writer import ExportWriter
from sma.phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text

if TYPE_CHECKING:  # pragma: no cover - type checking hint
    from .conftest import PerformanceMonitor


def _build_row(index: int) -> dict[str, str]:
    base_id = f"{index:010d}"
    return {
        "national_id": base_id,
        "counter": f"373{index:07d}",
        "first_name": sanitize_text(f"دانش‌آموز-{index}\u200c"),
        "last_name": sanitize_text(f"نمونه-{index}"),
        "gender": "1",
        "mobile": sanitize_phone("۰۹۱۲۳۴۵۶۷۸۹"),
        "reg_center": "1",
        "reg_status": "3",
        "group_code": "42",
        "student_type": "special",
        "school_code": "20001",
        "mentor_id": f"{index:08d}",
        "mentor_name": sanitize_text("سرپرست نمونه"),
        "mentor_mobile": sanitize_phone("۰۹۹۹۹۹۹۹۹۹۹"),
        "allocation_date": "1403-01-01",
        "year_code": "1403",
    }


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.usefixtures("performance_monitor")
def test_excel_generation_p95(performance_monitor: "PerformanceMonitor", tmp_path: Path) -> None:
    writer = ExportWriter(
        sensitive_columns=("national_id", "counter", "mobile", "mentor_id", "mentor_mobile"),
        chunk_size=20000,
    )
    fast = os.getenv("SMA_PERF_FAST", "").strip().lower() not in {"", "0", "false", "no"}
    target_rows = 10_240 if not fast else 512
    rows = [_build_row(i) for i in range(target_rows)]

    def _run() -> None:
        target = tmp_path / f"export-{uuid4().hex}"
        target.mkdir(parents=True, exist_ok=True)
        try:
            result = performance_monitor.run_with_retry(
                "excel_generation",
                lambda: writer.write_xlsx(rows, path_factory=lambda idx: target / f"chunk-{idx}.xlsx"),
            )
            assert result.total_rows == len(rows), (
                "تعداد ردیف‌های خروجی کمتر از مقدار انتظار است",
                performance_monitor.debug("excel_generation"),
            )
        finally:
            shutil.rmtree(target, ignore_errors=True)

    # Execute three warm samples to build a stable percentile baseline.
    warm_runs = 3 if not fast else 1
    for _ in range(warm_runs):
        _run()

    p95 = performance_monitor.percentile("excel_generation", 95)
    assert p95 <= 2.0, (
        "زمان تولید اکسل بیش از حد مجاز است",
        performance_monitor.debug("excel_generation"),
    )
    assert performance_monitor.peak_memory("excel_generation") <= 300 * 1024 * 1024, (
        "مصرف حافظه در تولید اکسل از سقف 300MB عبور کرد",
        performance_monitor.debug("excel_generation"),
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_concurrent_counter_pipeline(performance_monitor: "PerformanceMonitor") -> None:
    redis = performance_monitor.redis

    def _operation() -> None:
        keys: list[str] = []

        def _worker(slot: int) -> None:
            key = performance_monitor.key(f"req:{slot}")
            keys.append(key)
            redis.set(key, slot, ex=60)
            value = redis.get(key)
            assert value is not None, (
                "مقدار در ردیس یافت نشد",
                performance_monitor.debug("counter_pipeline"),
            )
            redis.delete(key)

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(_worker, idx) for idx in range(12)]
            for future in futures:
                future.result()

        leaked = [key for key in redis.keys("*") if isinstance(key, bytes) and key.decode("utf-8") in keys]
        assert not leaked, (
            "کلیدهای ردیس پس از اجرای همزمان پاک نشدند",
            performance_monitor.debug("counter_pipeline"),
        )

    for _ in range(3):
        performance_monitor.run_with_retry("counter_pipeline", _operation)

    p95 = performance_monitor.percentile("counter_pipeline", 95)
    assert p95 <= 0.25, (
        "p95 زنجیرهٔ RateLimit→Idempotency→Auth بیش از بودجهٔ 250ms است",
        performance_monitor.debug("counter_pipeline"),
    )
    assert performance_monitor.peak_memory("counter_pipeline") <= 64 * 1024 * 1024, (
        "حافظهٔ مصرفی زنجیرهٔ همزمانی بیش از حد مجاز است",
        performance_monitor.debug("counter_pipeline"),
    )


@pytest.mark.performance
@pytest.mark.benchmark
def test_large_streaming_throughput(performance_monitor: "PerformanceMonitor") -> None:
    chunk = b"1" * (1024 * 1024)  # 1 MiB
    iterations = 100  # 100 MiB total

    def _stream() -> None:
        buffer = io.BytesIO()
        for _ in range(iterations):
            buffer.write(chunk)
        assert buffer.getbuffer().nbytes >= len(chunk) * iterations, (
            "اندازهٔ جریان کمتر از ۱۰۰ مگابایت است",
            performance_monitor.debug("streaming_100mb"),
        )
        buffer.close()

    for _ in range(3):
        performance_monitor.run_with_retry("streaming_100mb", _stream)

    p95 = performance_monitor.percentile("streaming_100mb", 95)
    assert p95 <= 2.0, (
        "پهنای باند استریم ۱۰۰ مگابایتی از بودجهٔ ۲ ثانیه فراتر رفت",
        performance_monitor.debug("streaming_100mb"),
    )
    assert performance_monitor.peak_memory("streaming_100mb") <= 300 * 1024 * 1024, (
        "مصرف حافظهٔ جریان بیش از 300MB است",
        performance_monitor.debug("streaming_100mb"),
    )
