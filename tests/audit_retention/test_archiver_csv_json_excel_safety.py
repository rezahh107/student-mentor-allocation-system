from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("clean_state")

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.retention import AuditArchiveResult


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return list(reader)


@pytest.mark.usefixtures("frozen_time")
def test_csv_crlf_bom_formula_guard(archiver, insert_event, tz) -> None:
    ts = datetime(2024, 3, 12, 9, 15, tzinfo=tz)
    insert_event(
        {
            "ts": ts,
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "۰۱۲۳‌",
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": " گزارش",
            "resource_id": "=SUM(A1:A2)",
            "job_id": "۱۲۳۴۵",
            "request_id": "a3c5e8f0a1b2c3d4e5f6a7b8c9d0e1f2",
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    result: AuditArchiveResult = archiver.archive_month("2024_03")
    csv_rows = _read_csv(result.csv.path)
    assert result.row_count == 1
    assert csv_rows[0] == [
        "ts",
        "actor_role",
        "center_scope",
        "action",
        "resource_type",
        "resource_id",
        "job_id",
        "request_id",
        "outcome",
        "error_code",
        "artifact_sha256",
    ]
    data_row = csv_rows[1]
    assert data_row[2] == "0123"
    assert data_row[4] == "گزارش"
    assert data_row[5].startswith("'")
    assert b"\r\n" in result.csv.path.read_bytes()

    lines = result.json.path.read_text("utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["resource_id"].startswith("'")
    assert payload["center_scope"] == "0123"


@pytest.mark.usefixtures("frozen_time")
def test_manifest_hash_and_counts(archiver, insert_event, tz, archive_config) -> None:
    ts = datetime(2024, 3, 1, 12, tzinfo=tz)
    insert_event(
        {
            "ts": ts,
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": "۱۲۳",
            "action": AuditAction.EXPORT_FINALIZED,
            "resource_type": "report",
            "resource_id": "report-1",
            "job_id": None,
            "request_id": "b1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    result = archiver.archive_month("2024_03")
    manifest_path = archive_config.archive_root / "audit" / "2024" / "03" / "audit_archive_manifest.json"
    payload = json.loads(manifest_path.read_text("utf-8"))
    assert payload["row_count"] == 1
    csv_entry = next(item for item in payload["artifacts"] if item["type"] == "csv")
    json_entry = next(item for item in payload["artifacts"] if item["type"] == "json")
    assert csv_entry["sha256"] == result.csv.sha256
    assert json_entry["sha256"] == result.json.sha256


@pytest.mark.usefixtures("frozen_time")
def test_release_json_lists_new_archives(archiver, insert_event, release_manifest_path, tz) -> None:
    insert_event(
        {
            "ts": datetime(2024, 3, 2, 6, tzinfo=tz),
            "actor_role": AuditActorRole.ADMIN,
            "center_scope": None,
            "action": AuditAction.EXPORT_STARTED,
            "resource_type": "report",
            "resource_id": "r",
            "job_id": None,
            "request_id": "c1" * 16,
            "outcome": AuditOutcome.OK,
            "error_code": None,
            "artifact_sha256": None,
        }
    )

    archiver.archive_month("2024_03")
    manifest_data = json.loads(release_manifest_path.read_text("utf-8"))
    audit_artifacts = manifest_data["audit"]["artifacts"]
    names = {item["name"] for item in audit_artifacts}
    assert any(name.endswith(".csv") for name in names)
    assert any(name.endswith(".json") for name in names)
