from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from freezegun import freeze_time
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from zoneinfo import ZoneInfo

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.models import AuditEvent, Base
from src.audit.release_manifest import ReleaseManifest
from src.audit.retention import AuditArchiveConfig, AuditArchiver
from src.audit.service import AuditMetrics, build_metrics
from src.reliability.clock import Clock


FROZEN_INSTANT = datetime(2024, 3, 20, 8, 30, tzinfo=ZoneInfo("Asia/Tehran"))


@pytest.fixture(scope="function")
def tz() -> ZoneInfo:
    return ZoneInfo("Asia/Tehran")


@pytest.fixture(scope="function")
def frozen_time() -> Iterator[datetime]:
    with freeze_time("2024-03-20T08:30:00+03:30"):
        yield FROZEN_INSTANT


@pytest.fixture(scope="function")
def engine(tmp_path: Path) -> Iterator[Any]:
    db_path = tmp_path / "audit.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    if db_path.exists():
        db_path.unlink()


@pytest.fixture(scope="function")
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="function")
def insert_event(session_factory) -> Callable[[dict[str, Any]], int]:
    def factory(payload: dict[str, Any]) -> int:
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
def release_manifest_path(tmp_path: Path) -> Path:
    path = tmp_path / "release.json"
    path.write_text(json.dumps({"audit": {"artifacts": []}}), encoding="utf-8")
    return path


@pytest.fixture(scope="function")
def archive_config(tmp_path: Path) -> AuditArchiveConfig:
    return AuditArchiveConfig(archive_root=tmp_path / "archives", csv_bom=True)


@pytest.fixture(scope="function")
def clean_state(archive_config: AuditArchiveConfig) -> Iterator[None]:
    root = archive_config.archive_root
    if root.exists():
        for leftover in root.rglob("*.part"):
            leftover.unlink()
    yield
    if root.exists():
        for leftover in root.rglob("*.part"):
            leftover.unlink()


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
    return AuditArchiver(
        engine=engine,
        metrics=metrics,
        clock=clock,
        release_manifest=manifest,
        config=archive_config,
    )


def make_payload(
    *,
    ts: datetime,
    actor_role: AuditActorRole = AuditActorRole.ADMIN,
    center_scope: str | None = "۰۱۲۳",
    action: AuditAction = AuditAction.EXPORT_STARTED,
    resource_type: str = "report",
    resource_id: str = "=cmd|A1",
    job_id: str | None = None,
    request_id: str = "a3c5e8f0a1b2c3d4e5f6a7b8c9d0e1f2",
    outcome: AuditOutcome = AuditOutcome.OK,
    error_code: str | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "ts": ts,
        "actor_role": actor_role,
        "center_scope": center_scope,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "job_id": job_id,
        "request_id": request_id,
        "outcome": outcome,
        "error_code": error_code,
        "artifact_sha256": artifact_sha256,
    }


__all__ = ["archiver", "insert_event", "make_payload", "engine"]
