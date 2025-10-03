from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


class _ManifestRoster(SpecialSchoolsRoster):
    def is_special(self, year: int, school_code: int | None) -> bool:  # pragma: no cover - deterministic
        return bool(school_code and school_code % 2 == 0)


class _ManifestSource(ExporterDataSource):
    def __init__(self, rows: list[NormalizedStudentRow]) -> None:
        self._rows = rows

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):  # type: ignore[override]
        yield from self._rows


def _build_rows(now: datetime) -> list[NormalizedStudentRow]:
    tz = ZoneInfo("Asia/Tehran")
    aware = now.astimezone(tz)
    return [
        NormalizedStudentRow(
            national_id="2233445566",
            counter="243733211",
            first_name="زهرا",
            last_name="احمدی",
            gender=0,
            mobile="09012345679",
            reg_center=2,
            reg_status=1,
            group_code=202,
            student_type=0,
            school_code=654321,
            mentor_id="m-777",
            mentor_name="خانم مربی",
            mentor_mobile="09120000001",
            allocation_date=aware,
            year_code="1402",
            created_at=aware,
            id=2,
        )
    ]


def test_export_manifest_uses_injected_tehran_clock(tmp_path: Path) -> None:
    tz = ZoneInfo("Asia/Tehran")
    frozen = datetime(2024, 3, 20, 21, 45, 5, tzinfo=tz)
    rows = _build_rows(frozen)
    source = _ManifestSource(rows)
    roster = _ManifestRoster()
    exporter = ImportToSabtExporter(
        data_source=source,
        roster=roster,
        output_dir=tmp_path,
        profile=SABT_V1_PROFILE,
    )
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv"),
        snapshot=ExportSnapshot(marker="snapshot", created_at=frozen),
        clock_now=frozen,
    )
    assert isinstance(manifest, ExportManifest)
    assert manifest.generated_at == frozen
    manifest_path = tmp_path / "export_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == frozen.isoformat()
    assert payload["metadata"]["timestamp"] == frozen.strftime("%Y%m%d%H%M%S")
    assert payload["filters"]["year"] == 1402
    assert payload["filters"]["center"] == 1

