from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.clock import FrozenClock
from core.retry import RetryPolicy
from phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from phase6_import_to_sabt.models import (
    ExportExecutionStats,
    ExportFilters,
    ExportManifest,
    ExportOptions,
    ExportSnapshot,
    ExporterDataSource,
    NormalizedStudentRow,
    SABT_V1_PROFILE,
    SpecialSchoolsRoster,
)


class _Roster(SpecialSchoolsRoster):
    def is_special(self, year: int, school_code: int | None) -> bool:  # pragma: no cover - deterministic fake
        return False


@dataclass
class _SequenceSource(ExporterDataSource):
    rows: tuple[NormalizedStudentRow, ...]

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):  # type: ignore[override]
        yield from self.rows


class _DurationClock:
    def __init__(self, schedule: list[float]) -> None:
        self._schedule = schedule
        self._index = 0
        self._last = 0.0

    def __call__(self) -> float:
        if self._index < len(self._schedule):
            self._last = self._schedule[self._index]
            self._index += 1
        else:  # pragma: no cover - defensive fallback
            self._last += 0.01
        return self._last


def _build_rows(tz: ZoneInfo) -> tuple[NormalizedStudentRow, ...]:
    base = datetime(2024, 4, 1, 8, 0, tzinfo=tz)
    rows: list[NormalizedStudentRow] = []
    for index in range(100):
        aware = base.replace(minute=index % 60)
        rows.append(
            NormalizedStudentRow(
                national_id=f"00{index:08d}",
                counter=f"24373{index:04d}",
                first_name="علی",
                last_name="رضایی",
                gender=0,
                mobile="09012345678",
                reg_center=1,
                reg_status=1,
                group_code=101,
                student_type=0,
                school_code=123456,
                mentor_id="m-001",
                mentor_name="خانم راهنما",
                mentor_mobile="09120000000",
                allocation_date=aware,
                year_code="1402",
                created_at=aware,
                id=index + 1,
            )
        )
    return tuple(rows)


def test_p95_and_mem_with_overheads(tmp_path: Path) -> None:
    tz = ZoneInfo("Asia/Tehran")
    rows = _build_rows(tz)
    source = _SequenceSource(rows)
    roster = _Roster()
    frozen_clock = FrozenClock(timezone=tz)
    frozen_clock.set(datetime(2024, 4, 1, 8, 0, tzinfo=tz))
    policy = RetryPolicy(base_delay=0.01, factor=2.0, max_delay=0.05, max_attempts=3)
    exporter = ImportToSabtExporter(
        data_source=source,
        roster=roster,
        output_dir=tmp_path,
        profile=SABT_V1_PROFILE,
        clock=frozen_clock,
        retry_policy=policy,
    )
    durations = _DurationClock([0.0, 0.03, 0.03, 0.08, 0.08, 0.13, 0.13, 0.18])
    exporter._duration_clock = durations  # type: ignore[attr-defined]

    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(output_format="csv", chunk_size=50),
        snapshot=ExportSnapshot(marker="snapshot", created_at=frozen_clock.now()),
        clock_now=frozen_clock.now(),
        correlation_id="perf-budget",
    )

    assert isinstance(manifest, ExportManifest)
    assert manifest.total_rows == len(rows)
    stats = exporter.last_stats
    assert isinstance(stats, ExportExecutionStats)
    for phase, duration in stats.phase_durations.items():
        assert duration <= 0.2, {"phase": phase, "duration": duration}

    for file in manifest.files:
        assert file.byte_size < 150 * 1024 * 1024

    assert not list(tmp_path.glob("*.part"))
