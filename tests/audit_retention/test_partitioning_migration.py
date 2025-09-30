from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("clean_state")
from sqlalchemy import text

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.partitioning import ensure_monthly_partition_indexes


@pytest.mark.usefixtures("frozen_time")
def test_monthly_partitions_insert_only(engine, insert_event, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 4, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENTER",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "res",
            "job_id": None,
            "request_id": "e1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    created = ensure_monthly_partition_indexes(
        engine,
        start=datetime(2024, 1, 1, tzinfo=tz),
        end=datetime(2024, 5, 1, tzinfo=tz),
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_audit_events_month_%'")
        ).fetchall()
        names = {row[0] for row in rows}
    assert set(created).issubset(names)

    with pytest.raises(Exception) as excinfo:
        with engine.connect() as conn:
            conn.execute(text("UPDATE audit_events SET action='EXPORT_FINALIZED'"))
    assert "AUDIT_APPEND_ONLY" in str(excinfo.value)
