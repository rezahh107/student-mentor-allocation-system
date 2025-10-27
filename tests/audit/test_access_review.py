from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.repository import AuditRepository
from sma.audit.service import AuditService, build_metrics
from sma.reliability.clock import Clock

from reports.access_review import generate_access_review


def test_access_review_generator(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    repository = AuditRepository(engine)
    asyncio.run(repository.init())
    clock = Clock(timezone=ZoneInfo("Asia/Tehran"), _now_factory=lambda: datetime(2024, 5, 1, tzinfo=timezone.utc))
    metrics = build_metrics()
    service = AuditService(repository=repository, clock=clock, metrics=metrics)

    asyncio.run(
        service.record_event(
            actor_role=AuditActorRole.ADMIN,
            center_scope=None,
            action=AuditAction.UPLOAD_CREATED,
            resource_type="upload",
            resource_id="file-1",
            request_id="a" * 32,
            outcome=AuditOutcome.OK,
        )
    )
    asyncio.run(
        service.record_event(
            actor_role=AuditActorRole.MANAGER,
            center_scope="123",
            action=AuditAction.EXPORT_FINALIZED,
            resource_type="export",
            resource_id="exp-1",
            request_id="b" * 32,
            outcome=AuditOutcome.ERROR,
        )
    )

    report_path = asyncio.run(generate_access_review(service, output_dir=tmp_path, month="2024-05"))
    assert report_path.exists()
    payload = json.loads(report_path.read_text("utf-8"))
    assert payload["total_events"] == 2
    assert payload["summary"]["by_role"]["ADMIN"] == 1
    assert payload["summary"]["by_outcome"]["ERROR"] == 1

