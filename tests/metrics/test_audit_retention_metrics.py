from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("clean_state")

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.retention import AuditArchiveConfig, AuditRetentionEnforcer


@pytest.mark.usefixtures("frozen_time")
def test_exposes_audit_metrics_labels(archiver, insert_event, metrics, tz, archive_config, engine) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 10, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENTER",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "res",
            "job_id": None,
            "request_id": "f1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    archiver.archive_month("2024_03")
    retention_cfg = AuditArchiveConfig(
        archive_root=archive_config.archive_root,
        csv_bom=True,
        retention_age_days=1,
    )
    enforcer = AuditRetentionEnforcer(
        engine=engine,
        archiver=archiver,
        metrics=metrics,
        config=retention_cfg,
    )
    enforcer.enforce(dry_run=False)

    registry = metrics.registry
    success_count = registry.get_sample_value(
        "audit_archive_runs_total",
        {"status": "success", "month": "2024_03"},
    )
    purge_count = registry.get_sample_value(
        "audit_retention_purges_total",
        {"reason": "age"},
    )
    assert success_count == 1.0
    assert purge_count == 1.0
