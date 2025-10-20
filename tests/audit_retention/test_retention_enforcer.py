from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("clean_state")
from sqlalchemy import text

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.retention import AuditArchiveConfig, AuditRetentionEnforcer


@pytest.mark.usefixtures("frozen_time")
def test_enforce_only_after_valid_archive(archiver, insert_event, tz, archive_config, engine, metrics) -> None:
    ts = datetime(2024, 3, 5, 10, tzinfo=tz)
    insert_event(
        {
            "ts": ts,
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "۱۰۰",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "id-1",
            "job_id": None,
            "request_id": "d1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    archiver.archive_month("2024_03")
    retention_cfg = AuditArchiveConfig(
        archive_root=archive_config.archive_root,
        csv_bom=True,
        retention_age_days=5,
        retention_age_months=None,
        retention_size_bytes=None,
    )
    enforcer = AuditRetentionEnforcer(
        engine=engine,
        archiver=archiver,
        metrics=metrics,
        config=retention_cfg,
    )

    report = enforcer.enforce(dry_run=True)
    assert report["dry_run"], "expected dry run plan"
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one()
    enforce_report = enforcer.enforce(dry_run=False)
    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one()
    assert before == 1
    assert after == 0
    assert enforce_report["enforced"], "expected enforcement entries"
