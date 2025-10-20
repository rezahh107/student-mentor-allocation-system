from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sma.core.retry import RetryPolicy
from sma.phase6_import_to_sabt.exporter_service import ImportToSabtExporter, atomic_writer
from sma.phase6_import_to_sabt.models import (
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


class _Source(ExporterDataSource):
    def __init__(self, row: NormalizedStudentRow) -> None:
        self._row = row

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot):  # type: ignore[override]
        yield self._row


def _row(now: datetime) -> NormalizedStudentRow:
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
        allocation_date=now,
        year_code="1402",
        created_at=now,
        id=1,
    )


def test_finalize_retry_keeps_manifest_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tz = ZoneInfo("Asia/Tehran")
    now = datetime(2024, 3, 21, 12, 0, tzinfo=tz)
    source = _Source(_row(now))
    roster = _Roster()
    policy = RetryPolicy(base_delay=0.01, factor=2.0, max_delay=0.05, max_attempts=3)
    exporter = ImportToSabtExporter(
        data_source=source,
        roster=roster,
        output_dir=tmp_path,
        profile=SABT_V1_PROFILE,
        retry_policy=policy,
    )
    exporter._duration_clock = lambda: 0.0  # type: ignore[attr-defined]

    state = {"failures": 0}
    def flaky_atomic_writer(path: Path, *args, **kwargs):
        ctx = atomic_writer(path, *args, **kwargs)

        class _Wrapper:
            def __enter__(self):
                handle = ctx.__enter__()
                if path.name == "export_manifest.json" and state["failures"] == 0:
                    state["failures"] += 1
                    raise OSError("fsync failure")
                return handle

            def __exit__(self, exc_type, exc, tb):
                return ctx.__exit__(exc_type, exc, tb)

        return _Wrapper()

    monkeypatch.setattr("phase6_import_to_sabt.exporter_service.atomic_writer", flaky_atomic_writer)

    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(output_format="csv"),
        snapshot=ExportSnapshot(marker="snapshot", created_at=now),
        clock_now=now,
        correlation_id="retry-manifest",
    )

    assert isinstance(manifest, ExportManifest)
    assert state["failures"] == 1
    assert not list(tmp_path.glob("*.part"))

    manifest_path = tmp_path / "export_manifest.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == now.isoformat()
    assert payload["files"], payload

    first_file = payload["files"][0]
    artifact_path = tmp_path / first_file["name"]
    assert artifact_path.exists(), artifact_path
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert first_file["sha256"] == digest
    assert manifest.files[0].sha256 == digest
    assert manifest.total_rows == first_file["row_count"]
