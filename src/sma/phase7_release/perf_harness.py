"""Deterministic performance harness for ImportToSabt exports."""
from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import psutil

from sma.phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from sma.phase6_import_to_sabt.models import (
    ExportFilters,
    ExportOptions,
    ExportSnapshot,
    ExporterDataSource,
    NormalizedStudentRow,
)
from sma.phase6_import_to_sabt.roster import InMemoryRoster
from sma.shared.counter_rules import COUNTER_PREFIX_MAP

from .atomic import atomic_write


@dataclass(frozen=True)
class PerfBaseline:
    """Summary of the performance harness run."""

    export_p95_s: float
    peak_rss_mb: float

    def to_dict(self) -> dict[str, float]:
        return {
            "export_p95_s": round(self.export_p95_s, 4),
            "peak_rss_mb": round(self.peak_rss_mb, 4),
        }


class _SyntheticDataSource(ExporterDataSource):
    def __init__(self, total: int) -> None:
        self._total = total

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):  # type: ignore[override]
        base_created = datetime(2023, 1, 1, tzinfo=timezone.utc)
        for idx in range(1, self._total + 1):
            counter_core = COUNTER_PREFIX_MAP[idx % 2]
            counter = f"{str(filters.year)[-2:]}{counter_core}{idx % 10000:04d}"
            yield NormalizedStudentRow(
                national_id=f"{idx:010d}",
                counter=counter,
                first_name="علی",
                last_name="رضا",
                gender=idx % 2,
                mobile="09123456789",
                reg_center=idx % 3,
                reg_status=1,
                group_code=idx % 7,
                student_type=0,
                school_code=123456,
                mentor_id=f"M{idx % 500:04d}",
                mentor_name="راهنما",
                mentor_mobile="09120000000",
                allocation_date=base_created,
                year_code=str(filters.year),
                created_at=base_created + timedelta(seconds=idx % 60),
                id=idx,
            )


class PerfHarness:
    """Execute the exporter against a synthetic dataset and capture budgets."""

    def __init__(
        self,
        *,
        rows: int = 100_000,
        chunk_size: int = 50_000,
        perf_clock: Callable[[], float] | None = None,
        process_factory: Callable[[], psutil.Process] | None = None,
    ) -> None:
        self._rows = rows
        self._chunk_size = chunk_size
        self._perf_clock = perf_clock or time.perf_counter
        self._process_factory = process_factory or (lambda: psutil.Process(os.getpid()))

    def run(self, *, report_path: Path) -> PerfBaseline:
        report_path = Path(report_path)
        tmp_dir = report_path.parent / "perf_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        exporter = ImportToSabtExporter(
            data_source=_SyntheticDataSource(self._rows),
            roster=InMemoryRoster({1402: {123456}}),
            output_dir=tmp_dir,
        )

        filters = ExportFilters(year=1402, center=None)
        snapshot = ExportSnapshot(
            marker="perf-baseline",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        options = ExportOptions(chunk_size=self._chunk_size, output_format="csv")

        start = self._perf_clock()
        manifest = exporter.run(
            filters=filters,
            options=options,
            snapshot=snapshot,
            clock_now=snapshot.created_at,
        )
        end = self._perf_clock()
        duration = max(0.0, end - start)

        gc.collect()
        process = self._process_factory()
        rss_bytes = process.memory_info().rss
        baseline = PerfBaseline(export_p95_s=duration or 0.001, peak_rss_mb=rss_bytes / (1024 * 1024))

        payload = {
            "rows": manifest.total_rows,
            "files": [file.name for file in manifest.files],
            **baseline.to_dict(),
        }
        atomic_write(report_path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

        for file in tmp_dir.glob("*"):
            file.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:  # pragma: no cover - directory already removed
            pass

        return baseline


__all__ = ["PerfHarness", "PerfBaseline"]
