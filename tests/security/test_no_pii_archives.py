from __future__ import annotations

import re
from datetime import datetime

import pytest

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome


@pytest.mark.usefixtures("frozen_time")
def test_no_pii_in_archived_rows(archiver, insert_event, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 9, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "1234567890",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "user-9876543210",
            "job_id": None,
            "request_id": "f2" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    result = archiver.archive_month("2024_03")
    csv_data = result.csv.path.read_text("utf-8")
    json_data = result.json.path.read_text("utf-8")
    pii_pattern = re.compile(r"\b\d{10}\b")
    assert not pii_pattern.search(csv_data)
    assert not pii_pattern.search(json_data)
    assert "masked:" in csv_data
    assert "masked:" in json_data
