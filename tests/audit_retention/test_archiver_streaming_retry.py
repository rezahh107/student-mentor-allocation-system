from __future__ import annotations

from datetime import datetime

import pytest

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.retention import ArchiveFailure


@pytest.mark.usefixtures("clean_state", "frozen_time")
def test_streaming_no_buffer_oom(monkeypatch, archiver, insert_event, tz) -> None:
    for index in range(16):
        insert_event(
            {
                "ts": datetime(2024, 3, 5, 8, 30 + index, tzinfo=tz),
                "actor_role": AuditActorRole.ADMIN,
                "center_scope": "۰۱۲۳",
                "action": AuditAction.EXPORT_STARTED,
                "resource_type": "report",
                "resource_id": f"item-{index}",
                "job_id": None,
                "request_id": f"req{index:02d}".ljust(32, "f"),
                "outcome": AuditOutcome.OK,
                "error_code": None,
                "artifact_sha256": None,
            }
        )

    def fail_list(*args, **kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("list() should not be invoked during streaming export")

    monkeypatch.setattr("sma.audit.retention.list", fail_list, raising=False)

    result = archiver.archive_month("2024_03")
    assert result.row_count == 16
    assert result.csv.path.exists()
    assert result.json.path.exists()


@pytest.mark.usefixtures("clean_state", "frozen_time")
def test_archiver_emits_retry_metrics(monkeypatch, archiver, insert_event, metrics, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 10, 12, 0, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENTER",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "res",
            "job_id": None,
            "request_id": "retry".ljust(32, "e"),
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    original = archiver._write_artifacts
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("transient write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(archiver, "_write_artifacts", flaky)

    result = archiver.archive_month("2024_03")
    assert result.row_count == 1

    attempts_value = metrics.registry.get_sample_value(
        "audit_retry_attempts_total",
        {"stage": "archive_write"},
    )
    assert attempts_value == 1.0


@pytest.mark.usefixtures("clean_state", "frozen_time")
def test_archiver_retries_exhaustion(monkeypatch, archiver, insert_event, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 11, 9, 15, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "CENTER",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "boom",
            "job_id": None,
            "request_id": "fail".ljust(32, "0"),
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
