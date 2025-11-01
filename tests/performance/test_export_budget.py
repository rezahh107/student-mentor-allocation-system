"""Performance budget validation for 100k-row XLSX exports."""

from __future__ import annotations

import json
import math
import os
import time
import tracemalloc
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from src.sma.export.excel_writer import EXPORT_COLUMNS, ExportWriter

P95_BUDGET_SECONDS = 15.0
P99_BUDGET_SECONDS = 20.0
MEMORY_BUDGET_MB = 150.0
DEFAULT_ATTEMPTS = 5
DEFAULT_ROWS = 100_000
DEFAULT_CHUNK = 5_000


def _percentile(samples: Iterable[float], percentile: float) -> float:
    data = sorted(samples)
    if not data:
        return 0.0
    rank = max(0, math.ceil((percentile / 100.0) * len(data)) - 1)
    return data[min(rank, len(data) - 1)]


def _student_rows(total: int) -> Iterator[Mapping[str, Any]]:
    for index in range(total):
        base = f"{index:010d}"
        yield {
            "national_id": base,
            "counter": f"{index:09d}",
            "first_name": f"دانش‌آموز-{index}",
            "last_name": (
                "=HYPERLINK(\"https://example.com\")"
                if index % 10 == 0
                else f"نمونه-{index}"
            ),
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


def _artifact_path() -> Path:
    override = os.getenv("PYTEST_PERF_SUMMARY", "")
    if override:
        return Path(override)
    root = Path(os.getenv("PYTEST_PERF_ARTIFACTS", "test-results"))
    return root / "export_perf.json"


def _sensitive_columns() -> tuple[str, ...]:
    guarded = {
        "national_id",
        "counter",
        "mobile",
        "mentor_id",
        "mentor_mobile",
        "school_code",
    }
    return tuple(column for column in EXPORT_COLUMNS if column in guarded)


def test_export_xlsx_100k_budget(tmp_path: Path) -> None:
    try:
        total_rows = int(os.getenv("SMA_PERF_SAMPLE_SIZE", str(DEFAULT_ROWS)))
    except ValueError:
        total_rows = DEFAULT_ROWS
    total_rows = max(DEFAULT_ROWS, total_rows)
    attempts = int(os.getenv("SMA_PERF_ATTEMPTS", str(DEFAULT_ATTEMPTS)))
    attempts = max(1, attempts)
    chunk_size = int(os.getenv("SMA_PERF_CHUNK", str(DEFAULT_CHUNK)))

    writer = ExportWriter(sensitive_columns=_sensitive_columns(), chunk_size=chunk_size)

    durations: list[float] = []
    peak_bytes = 0
    tracemalloc.start()
    try:
        for attempt in range(attempts):
            target = tmp_path / f"export-{attempt}.xlsx"
            start = time.perf_counter()
            result = writer.write_xlsx(
                _student_rows(total_rows),
                path_factory=lambda _index, target=target: target,
            )
            duration = time.perf_counter() - start
            durations.append(duration)
            _, peak = tracemalloc.get_traced_memory()
            peak_bytes = max(peak_bytes, peak)
            assert result.total_rows == total_rows
            assert result.files[0].row_count == total_rows
    finally:
        tracemalloc.stop()

    assert len(durations) == attempts, "Performance harness must record every attempt"

    p95 = _percentile(durations, 95)
    p99 = _percentile(durations, 99)
    peak_mb = peak_bytes / (1024 * 1024)

    metrics = {
        "label": "export_100k_budget",
        "samples": len(durations),
        "durations": durations,
        "p95_seconds": p95,
        "p99_seconds": p99,
        "latency_p95_seconds": p95,
        "latency_p99_seconds": p99,
        "peak_memory_mb": peak_mb,
        "peak_mem_bytes": peak_bytes,
        "rows_per_attempt": total_rows,
        "budgets": {
            "p95_seconds": P95_BUDGET_SECONDS,
            "p99_seconds": P99_BUDGET_SECONDS,
            "peak_memory_mb": MEMORY_BUDGET_MB,
        },
    }

    artifact = _artifact_path()
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    m = metrics
    p95_budget = m["latency_p95_seconds"]
    p99_budget = m["latency_p99_seconds"]
    peak_bytes = m["peak_mem_bytes"]

    assert p95_budget < P95_BUDGET_SECONDS, f"p95={p95_budget:.2f}s"
    assert p99_budget < P99_BUDGET_SECONDS, f"p99={p99_budget:.2f}s"
    assert peak_bytes < int(MEMORY_BUDGET_MB * 1024 * 1024), f"peak={peak_bytes}B"
