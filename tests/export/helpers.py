from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.api import HMACSignedURLProvider, create_export_api
from phase6_import_to_sabt.clock import Clock, FixedClock, ensure_clock
from phase6_import_to_sabt.data_source import InMemoryDataSource
from phase6_import_to_sabt.exporter import ImportToSabtExporter
from phase6_import_to_sabt.job_runner import DeterministicRedis, ExportJobRunner
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.models import NormalizedStudentRow
from phase6_import_to_sabt.roster import InMemoryRoster
from phase7_release.deploy import ReadinessGate
from src.shared.counter_rules import gender_prefix


def make_row(
    *,
    idx: int,
    year: int = 1402,
    center: int = 1,
    group_code: int = 10,
    school_code: int | None = 123456,
    gender: int = 0,
    created_at: datetime | None = None,
) -> NormalizedStudentRow:
    created = created_at or datetime(2023, 7, 1, 12, 0, tzinfo=timezone.utc)
    seq = idx % 10_000
    mobile_seq = idx % 1_000_000_000
    mentor_seq = idx % 10_000
    mentor_mobile_seq = idx % 100_000
    return NormalizedStudentRow(
        national_id=f"{idx:010d}",
        counter=f"{str(year)[-2:]}{gender_prefix(gender)}{seq:04d}",
        first_name=f"Name{idx}",
        last_name=f"Surname{idx}",
        gender=gender,
        mobile=f"09{mobile_seq:09d}",
        reg_center=center,
        reg_status=1,
        group_code=group_code,
        student_type=0,
        school_code=school_code,
        mentor_id=f"M{mentor_seq:04d}",
        mentor_name=f"Mentor {idx}",
        mentor_mobile=f"09123{mentor_mobile_seq:05d}",
        allocation_date=datetime(2023, 7, 1, 12, 0, tzinfo=timezone.utc),
        year_code=str(year),
        created_at=created,
        id=idx,
    )


def build_exporter(tmp_path: Path, rows: Iterable[NormalizedStudentRow]) -> ImportToSabtExporter:
    roster = InMemoryRoster({1402: {123456, 654321}, 1401: {999999}})
    data_source = InMemoryDataSource(rows)
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=tmp_path,
    )
    return exporter


def build_job_runner(
    tmp_path: Path,
    rows: Iterable[NormalizedStudentRow],
    *,
    clock: Clock | Callable[[], datetime] | None = None,
):
    exporter = build_exporter(tmp_path, rows)
    redis = DeterministicRedis()
    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)
    default_clock = FixedClock(datetime(2023, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Tehran")))
    runner_clock = ensure_clock(clock, timezone="Asia/Tehran") if clock is not None else default_clock
    runner = ExportJobRunner(
        exporter=exporter,
        redis=redis,
        metrics=metrics,
        clock=runner_clock,
        sleeper=lambda _: None,
    )
    return runner, metrics


def build_export_app(
    tmp_path: Path,
    rows: Iterable[NormalizedStudentRow],
    *,
    clock: Clock | Callable[[], datetime] | None = None,
):
    runner, metrics = build_job_runner(tmp_path, rows, clock=clock)
    signer = HMACSignedURLProvider(secret="secret", clock=clock)
    gate = ReadinessGate(clock=lambda: 0.0)
    gate.record_cache_warm()
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    app = create_export_api(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=runner.logger,
        readiness_gate=gate,
    )
    return app, runner, metrics
