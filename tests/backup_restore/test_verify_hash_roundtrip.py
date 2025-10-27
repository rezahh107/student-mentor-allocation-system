from __future__ import annotations

import json
from datetime import datetime

import pytest

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.retention import ArchiveFailure, AuditArchiveConfig, AuditRetentionEnforcer


@pytest.mark.usefixtures("frozen_time")
def test_archive_in_backup_restore(archiver, insert_event, tz, archive_config, engine, metrics) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 7, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENT",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "res",
            "job_id": None,
            "request_id": "g1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    result = archiver.archive_month("2024_03")
    manifest_path = archive_config.archive_root / "audit" / "2024" / "03" / "archive_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    # corrupt manifest hash to force failure
    manifest["artifacts"][0]["sha256"] = "deadbeef"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

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

    with pytest.raises(ArchiveFailure):
        enforcer.enforce(dry_run=False)
