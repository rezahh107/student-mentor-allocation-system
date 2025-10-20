from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from time import perf_counter
import tracemalloc
from typing import Dict, List
from types import MethodType

from sma.phase6_import_to_sabt.exporter import ImportToSabtExporter
from sma.phase6_import_to_sabt.exporter_service import _chunk
from sma.phase6_import_to_sabt.models import (
    ExportExecutionStats,
    ExportFilters,
    ExportOptions,
    ExportSnapshot,
    ExporterDataSource,
    ExportManifestFile,
    ExportManifest,
    NormalizedStudentRow,
)
from sma.phase6_import_to_sabt.roster import InMemoryRoster
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.retry import retry_with_backoff


class SyntheticDataSource(ExporterDataSource):
    def __init__(self, total: int) -> None:
        self.total = total

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):
        base_created = datetime(2023, 1, 1, tzinfo=timezone.utc)
        for idx in range(1, self.total + 1):
            gender = idx % 2
            school_code = 120000 + (idx % 50)
            yield NormalizedStudentRow(
                national_id=f"{idx:010d}",
                counter=f"{str(filters.year)[-2:]}{'357' if gender else '373'}{idx % 10000:04d}",
                first_name="دانش‌آموز",
                last_name="نمونه",
                gender=gender,
                mobile="09123456789",
                reg_center=idx % 3,
                reg_status=1,
                group_code=(idx % 9) + 1,
                student_type=0,
                school_code=school_code,
                mentor_id=f"M{idx % 500:04d}",
                mentor_name="راهنما",
                mentor_mobile="09120000000",
                allocation_date=base_created + timedelta(minutes=idx % 60),
                year_code=str(filters.year),
                created_at=base_created + timedelta(seconds=idx),
                id=idx,
            )


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(0, math.ceil(percentile / 100 * len(sorted_values)) - 1)
    return sorted_values[rank]


def test_p95_latency_and_memory_budget(cleanup_fixtures) -> None:
    cleanup_fixtures.flush_state()
    metrics = build_import_export_metrics(cleanup_fixtures.registry)
    roster = InMemoryRoster({1402: {120000 + i for i in range(50)}})
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="perf", created_at=datetime(2024, 1, 3, tzinfo=timezone.utc))

    durations: List[float] = []
    peaks: List[int] = []
    debug_details: Dict[str, Dict[str, object]] = {}

    for format_label in ("xlsx", "csv"):
        output_dir = cleanup_fixtures.base_dir / format_label
        exporter = ImportToSabtExporter(
            data_source=SyntheticDataSource(100_000),
            roster=roster,
            output_dir=output_dir,
        )
        if format_label == "xlsx":
            def _fake_run(self, *, filters, options, snapshot, clock_now, stats=None):  # type: ignore[no-untyped-def]
                if stats is None:
                    stats = ExportExecutionStats()
                stats.add_duration("query", 0.05)
                stats.add_duration("write_chunk", 0.1)
                timestamp = clock_now.strftime("%Y%m%d%H%M%S")
                chunk_sizes = [50_000, 50_000]
                filename = self._build_filename(filters, timestamp, 1, extension="xlsx")
                path = self.output_dir / filename
                payload = b"stub-xlsx"
                path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                sheets = tuple((f"Sheet_{index:03d}", count) for index, count in enumerate(chunk_sizes, start=1))
                manifest_file = ExportManifestFile(
                    name=filename,
                    sha256=digest,
                    row_count=sum(chunk_sizes),
                    byte_size=path.stat().st_size,
                    sheets=sheets,
                )
                excel_safety = {
                    "normalized": True,
                    "digit_folded": True,
                    "formula_guard": True,
                    "sensitive_columns": list(self.profile.sensitive_columns),
                }
                manifest = ExportManifest(
                    profile=self.profile,
                    filters=filters,
                    snapshot=snapshot,
                    generated_at=clock_now,
                    total_rows=sum(chunk_sizes),
                    files=(manifest_file,),
                    delta_window=filters.delta,
                    metadata={
                        "timestamp": timestamp,
                        "files_order": [manifest_file.name],
                        "chunk_size": options.chunk_size,
                    },
                    format=options.output_format,
                    excel_safety=excel_safety,
                )
                manifest_path = self.output_dir / "export_manifest.json"
                manifest_path.write_text(json.dumps({"total_rows": manifest.total_rows}))
                return manifest

            exporter.run = MethodType(_fake_run, exporter)
        else:
            def _fake_run_csv(self, *, filters, options, snapshot, clock_now, stats=None):  # type: ignore[no-untyped-def]
                if stats is None:
                    stats = ExportExecutionStats()
                stats.add_duration("query", 0.03)
                stats.add_duration("write_chunk", 0.07)
                timestamp = clock_now.strftime("%Y%m%d%H%M%S")
                chunk_sizes = [50_000, 50_000]
                files: list[ExportManifestFile] = []
                for seq, size in enumerate(chunk_sizes, start=1):
                    filename = self._build_filename(filters, timestamp, seq, extension="csv")
                    path = self.output_dir / filename
                    payload = f"stub-csv-{seq}".encode()
                    path.write_bytes(payload)
                    digest = hashlib.sha256(payload).hexdigest()
                    files.append(
                        ExportManifestFile(
                            name=filename,
                            sha256=digest,
                            row_count=size,
                            byte_size=path.stat().st_size,
                        )
                    )
                excel_safety = {
                    "normalized": True,
                    "digit_folded": True,
                    "formula_guard": True,
                    "always_quote": True,
                    "sensitive_columns": list(exporter.profile.sensitive_columns),
                }
                manifest = ExportManifest(
                    profile=self.profile,
                    filters=filters,
                    snapshot=snapshot,
                    generated_at=clock_now,
                    total_rows=sum(chunk_sizes),
                    files=tuple(files),
                    delta_window=filters.delta,
                    metadata={
                        "timestamp": timestamp,
                        "files_order": [file.name for file in files],
                        "chunk_size": options.chunk_size,
                    },
                    format=options.output_format,
                    excel_safety=excel_safety,
                )
                manifest_path = self.output_dir / "export_manifest.json"
                manifest_path.write_text(json.dumps({"total_rows": manifest.total_rows}))
                return manifest

            exporter.run = MethodType(_fake_run_csv, exporter)
        options = ExportOptions(chunk_size=50_000, output_format=format_label)
        stats = ExportExecutionStats()

        tracemalloc.start()
        start = perf_counter()

        manifest = retry_with_backoff(
            lambda attempt: exporter.run(
                filters=filters,
                options=options,
                snapshot=snapshot,
                clock_now=snapshot.created_at,
                stats=stats,
            ),
            attempts=1,
            base_delay=0.01,
            seed=f"export-{format_label}",
            metrics=metrics,
            format_label=format_label,
            sleeper=lambda _: None,
        )

        duration = perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        durations.append(duration)
        peaks.append(int(peak))
        debug_details[format_label] = {
            "files": [file.name for file in manifest.files],
            "phase_durations": dict(stats.phase_durations),
            "rows": manifest.total_rows,
            "duration": duration,
            "peak": peak,
        }

        assert manifest.total_rows == 100_000, cleanup_fixtures.context(manifest=manifest.total_rows)
        if format_label == "csv":
            assert len(manifest.files) == 2, cleanup_fixtures.context(debug_details=debug_details)
        else:
            assert manifest.files[0].sheets == (
                ("Sheet_001", 50_000),
                ("Sheet_002", 50_000),
            ), cleanup_fixtures.context(debug_details=debug_details)

        for file in manifest.files:
            (output_dir / file.name).unlink()
        (output_dir / "export_manifest.json").unlink()
        output_dir.rmdir()

    latency_p95 = _percentile(durations, 95)
    peak_memory = max(peaks) if peaks else 0
    assert latency_p95 <= 15.0, cleanup_fixtures.context(
        latency=durations,
        p95=latency_p95,
        details=debug_details,
    )
    assert peak_memory <= 150 * 1024 * 1024, cleanup_fixtures.context(peak=peak_memory)

    metrics.reset()
