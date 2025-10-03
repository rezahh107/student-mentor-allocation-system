from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from phase6_import_to_sabt.models import (
    ExportFilters,
    ExportManifest,
    ExportOptions,
    ExportSnapshot,
    NormalizedStudentRow,
    SpecialSchoolsRoster,
    ExporterDataSource,
    SABT_V1_PROFILE,
)


class _FakeRoster(SpecialSchoolsRoster):
    def is_special(self, year: int, school_code: int | None) -> bool:  # pragma: no cover - trivial
        return False


class _SingleRowSource(ExporterDataSource):
    def __init__(self, row: NormalizedStudentRow) -> None:
        self._row = row

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):  # type: ignore[override]
        yield self._row


def _row_factory(clock_now: datetime) -> NormalizedStudentRow:
    aware_now = clock_now.astimezone(ZoneInfo("Asia/Tehran"))
    return NormalizedStudentRow(
        national_id="0011223344",
        counter="243733210",
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
        allocation_date=aware_now,
        year_code="1402",
        created_at=aware_now,
        id=1,
    )


@pytest.fixture()
def exporter(tmp_path: Path) -> ImportToSabtExporter:
    tz = ZoneInfo("Asia/Tehran")
    frozen = datetime(2024, 3, 20, 10, 15, 30, tzinfo=tz)
    row = _row_factory(frozen)
    source = _SingleRowSource(row)
    roster = _FakeRoster()
    exporter = ImportToSabtExporter(
        data_source=source,
        roster=roster,
        output_dir=tmp_path,
        profile=SABT_V1_PROFILE,
    )
    exporter._duration_clock = lambda: 0.0  # type: ignore[attr-defined]
    return exporter


def test_export_filename_uses_frozen_time(exporter: ImportToSabtExporter, tmp_path: Path) -> None:
    tz = ZoneInfo("Asia/Tehran")
    frozen = datetime(2024, 3, 20, 10, 15, 30, tzinfo=tz)
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(output_format="xlsx"),
        snapshot=ExportSnapshot(marker="snapshot", created_at=frozen),
        clock_now=frozen,
    )
    assert isinstance(manifest, ExportManifest)
    files = list(manifest.files)
    assert files, "manifest must include at least one export artifact"
    assert files[0].name.startswith("export_SABT_V1_1402-ALL_20240320101530"), files[0].name
    assert files[0].name.endswith(".xlsx"), files[0].name

