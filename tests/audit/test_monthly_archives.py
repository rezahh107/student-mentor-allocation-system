from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.models import AuditEvent, Base
from sma.audit.release_manifest import ReleaseManifest
from sma.audit.repository import AuditRepository
from sma.audit.retention import AuditArchiveConfig, AuditArchiver
from sma.audit.service import AuditMetrics, AuditService, build_metrics
from sma.reliability.clock import Clock

FROZEN_INSTANT = datetime(2024, 3, 20, 8, 30, tzinfo=ZoneInfo("Asia/Tehran"))


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise TypeError("sqlite adapters require timezone-aware datetimes")
    return value.isoformat()


def _convert_datetime(raw: bytes) -> datetime:
    text = raw.decode("utf-8")
    return datetime.fromisoformat(text)


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("timestamp", _convert_datetime)
sqlite3.register_converter("datetime", _convert_datetime)


@pytest.fixture(scope="function")
def tz() -> ZoneInfo:
    return ZoneInfo("Asia/Tehran")


@pytest.fixture(scope="function")
def frozen_time() -> datetime:
    with freeze_time("2024-03-20T08:30:00+03:30"):
        yield FROZEN_INSTANT


@pytest.fixture(scope="function")
def engine(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
            "detect_types": sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        },
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="function")
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="function")
def insert_event(session_factory) -> Callable[[dict[str, object]], int]:
    def factory(payload: dict[str, object]) -> int:
        with session_factory() as session:
            event = AuditEvent(**payload)
            session.add(event)
            session.commit()
            return event.id

    return factory


@pytest.fixture(scope="function")
def metrics() -> AuditMetrics:
    registry = CollectorRegistry()
    return build_metrics(registry=registry)


@pytest.fixture(scope="function")
def archive_config(tmp_path: Path) -> AuditArchiveConfig:
    return AuditArchiveConfig(archive_root=tmp_path / "archives", csv_bom=True)


@pytest.fixture(scope="function")
def release_manifest_path(tmp_path: Path) -> Path:
    path = tmp_path / "release.json"
    path.write_text(json.dumps({"audit": {"artifacts": []}}), encoding="utf-8")
    return path


@pytest.fixture(scope="function")
def clock(tz: ZoneInfo) -> Clock:
    return Clock(tz)


@pytest.fixture(scope="function")
def archiver(
    engine,
    metrics: AuditMetrics,
    clock: Clock,
    archive_config: AuditArchiveConfig,
    release_manifest_path: Path,
) -> AuditArchiver:
    manifest = ReleaseManifest(release_manifest_path)
    repository = AuditRepository(engine)
    asyncio.run(repository.init())
    service = AuditService(repository=repository, clock=clock, metrics=metrics)
    archiver = AuditArchiver(
        engine=engine,
        metrics=metrics,
        clock=clock,
        release_manifest=manifest,
        config=archive_config,
    )
    archiver._service = service  # type: ignore[attr-defined]
    return archiver


@pytest.mark.usefixtures("frozen_time")
def test_archive_manifest_contains_monthly_summary(archiver, insert_event, tz, archive_config) -> None:
    insert_event(
        {
            "ts": datetime(2024, 4, 3, 9, tzinfo=tz),
            "actor_role": AuditActorRole.MANAGER,
            "center_scope": "0456",
            "action": AuditAction.UPLOAD_ACTIVATED,
            "resource_type": "upload",
            "resource_id": "roster",
            "job_id": "job-1",
            "request_id": "d1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": "a" * 64,
        }
    )

    result = archiver.archive_month("2024_04")
    manifest_path = archive_config.archive_root / "audit" / "2024" / "04" / "archive_manifest.json"
    payload = json.loads(manifest_path.read_text("utf-8"))
    assert payload["row_count"] == result.row_count
    assert payload["month"] == "2024_04"
    csv_entry = next(item for item in payload["artifacts"] if item["type"] == "csv")
    assert csv_entry["sha256"] == result.csv.sha256

