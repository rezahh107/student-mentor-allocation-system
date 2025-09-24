# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from src.infrastructure.persistence.models import StudentModel
from src.phase2_counter_service.backfill import run_backfill

from .conftest import seed_student


def _write_csv(path: Path, rows):
    fieldnames = ["national_id", "gender", "year_code"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_backfill_dry_run_and_apply(tmp_path, service, session):
    rows = [
        {"national_id": "1234567894", "gender": 0, "year_code": "25"},
        {"national_id": "1234567895", "gender": 1, "year_code": "25"},
        {"national_id": "1234567896", "gender": 0, "year_code": "26"},
    ]
    for row in rows:
        seed_student(session, national_id=row["national_id"], gender=row["gender"])
    seed_student(session, national_id="1234567897", gender=1, counter="253571111")
    csv_path = tmp_path / "backfill.csv"
    _write_csv(csv_path, rows + [{"national_id": "1234567897", "gender": 1, "year_code": "25"}])

    stats_dry = run_backfill(service, csv_path, chunk_size=2, apply=False)
    assert stats_dry.dry_run is True
    assert stats_dry.applied == 0
    assert stats_dry.skipped == 3
    assert stats_dry.reused == 1
    assert stats_dry.prefix_mismatches == 0

    stats_apply = run_backfill(service, csv_path, chunk_size=2, apply=True)
    assert stats_apply.dry_run is False
    assert stats_apply.applied == 3
    assert stats_apply.reused == 1
    assert stats_apply.prefix_mismatches == 0

    assigned_rows = session.execute(
        select(StudentModel).where(StudentModel.national_id.in_([r['national_id'] for r in rows]))
    ).scalars().all()
    assigned = {row.national_id: row.counter for row in assigned_rows}
    assert all(counter is not None for counter in assigned.values())


def test_backfill_streaming_large_file(tmp_path, service, session):
    bulk_rows = [
        {"national_id": f"90{i:08d}", "gender": i % 2, "year_code": f"{25 + (i % 2):02d}"}
        for i in range(200)
    ]
    for row in bulk_rows:
        seed_student(session, national_id=row["national_id"], gender=row["gender"])
    csv_path = tmp_path / "bulk.csv"
    _write_csv(csv_path, bulk_rows)

    stats = run_backfill(service, csv_path, chunk_size=17, apply=False)
    assert stats.total_rows == 200
    assert stats.skipped == 200
    assert stats.applied == 0
    assert stats.prefix_mismatches == 0


def test_backfill_reports_prefix_mismatch(tmp_path, service, session, caplog):
    seed_student(
        session,
        national_id="1234567800",
        gender=0,
        counter="263571234",
    )
    csv_path = tmp_path / "mismatch.csv"
    _write_csv(
        csv_path,
        [
            {"national_id": "1234567800", "gender": 0, "year_code": "26"},
        ],
    )

    with caplog.at_level("WARNING"):
        stats = run_backfill(service, csv_path, chunk_size=1, apply=False)

    assert stats.prefix_mismatches == 1
    assert any("backfill_prefix_mismatch" in record.message for record in caplog.records)
