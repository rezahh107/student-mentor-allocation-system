from __future__ import annotations

import gc
import os
from datetime import datetime, timedelta, timezone
from time import perf_counter

import psutil

from phase6_import_to_sabt.exporter import ImportToSabtExporter
from phase6_import_to_sabt.models import (
    ExportFilters,
    ExportOptions,
    ExportSnapshot,
    ExporterDataSource,
    NormalizedStudentRow,
)
from phase6_import_to_sabt.roster import InMemoryRoster


class SyntheticDataSource(ExporterDataSource):
    def __init__(self, total: int) -> None:
        self.total = total

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):
        base_created = datetime(2023, 1, 1, tzinfo=timezone.utc)
        for idx in range(1, self.total + 1):
            yield NormalizedStudentRow(
                national_id=f"{idx:010d}",
                counter=f"{str(filters.year)[-2:]}{'357' if idx % 2 else '373'}{idx % 10000:04d}",
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


def _build_exporter(tmp_path, total: int) -> ImportToSabtExporter:
    roster = InMemoryRoster({1402: {123456}})
    data_source = SyntheticDataSource(total)
    return ImportToSabtExporter(data_source=data_source, roster=roster, output_dir=tmp_path)


def test_p95_and_mem_budget(tmp_path) -> None:
    exporter = _build_exporter(tmp_path, 100_000)
    snapshot = ExportSnapshot(marker="perf", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    filters = ExportFilters(year=1402, center=None)
    options = ExportOptions(chunk_size=50_000, output_format="csv")

    start = perf_counter()
    manifest = exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=snapshot.created_at)
    duration = perf_counter() - start

    gc.collect()
    rss = psutil.Process(os.getpid()).memory_info().rss

    assert duration <= 15.0, {"duration": duration, "files": [file.name for file in manifest.files]}
    assert rss <= 150 * 1024 * 1024, {"rss": rss, "rows": manifest.total_rows}
    assert manifest.total_rows == 100_000
    assert len(manifest.files) == 2

    for file in tmp_path.glob("export_*.csv"):
        file.unlink(missing_ok=True)
    (tmp_path / "export_manifest.json").unlink(missing_ok=True)
