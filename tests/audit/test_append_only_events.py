from __future__ import annotations

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.repository import AuditQuery, AuditRepository
from sma.audit.service import AuditService, build_metrics
from sma.reliability.clock import Clock


@pytest.fixture
def audit_env(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    repository = AuditRepository(engine)
    asyncio.run(repository.init())
    clock = Clock(timezone=ZoneInfo("Asia/Tehran"), _now_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
    metrics = build_metrics()
    service = AuditService(repository=repository, clock=clock, metrics=metrics)
    env = SimpleNamespace(
        service=service,
        engine=engine,
        debug_context=lambda: {"engine": "sqlite", "tz": "Asia/Tehran"},
    )
    try:
        yield env
    finally:
        engine.dispose()


def test_audit_table_is_append_only(audit_env) -> None:
    service = audit_env.service
    rid = "123e4567-e89b-12d3-a456-426614174001"

    event_id = asyncio.run(
        service.record_event(
            actor_role=AuditActorRole.ADMIN,
            center_scope=None,
            action=AuditAction.UPLOAD_CREATED,
            resource_type="upload",
            resource_id="file.csv",
            request_id=rid,
            outcome=AuditOutcome.OK,
        )
    )

    def _exec(statement: str) -> None:
        with audit_env.engine.begin() as conn:
            conn.execute(text(statement), {"id": event_id})

    with pytest.raises(Exception):
        asyncio.run(asyncio.to_thread(_exec, "UPDATE audit_events SET outcome='ERROR' WHERE id=:id"))

    with pytest.raises(Exception):
        asyncio.run(asyncio.to_thread(_exec, "DELETE FROM audit_events WHERE id=:id"))

    events = asyncio.run(service.list_events(AuditQuery(limit=5)))
    assert any(event.id == event_id for event in events)

