from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("clean_state")

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.retention import ArchiveFailure


@pytest.mark.usefixtures("clean_state", "frozen_time")
def test_retry_counters_emitted(monkeypatch, archiver, insert_event, metrics, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 20, 10, 0, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENTER",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "res",
            "job_id": None,
            "request_id": "boom".ljust(32, "a"),
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    def always_fail(*args, **kwargs):
        raise OSError("permanent failure")

    monkeypatch.setattr(archiver, "_write_artifacts", always_fail)

    with pytest.raises(ArchiveFailure):
        archiver.archive_month("2024_03")

    attempts_value = metrics.registry.get_sample_value(
        "audit_retry_attempts_total",
        {"stage": "archive_write"},
    )
    exhausted_value = metrics.registry.get_sample_value(
        "audit_retry_exhausted_total",
        {"stage": "archive_write"},
    )

    assert attempts_value == float(archiver._config.retry_attempts)
    assert exhausted_value == 1.0
