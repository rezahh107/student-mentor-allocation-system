from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.reliability import Clock, ReliabilityMetrics, RetentionEnforcer
from src.reliability.config import RetentionConfig
from src.reliability.logging_utils import JSONLogger


class FakeNow:
    def __init__(self) -> None:
        self.value = datetime(2024, 4, 1, tzinfo=ZoneInfo("UTC"))

    def __call__(self) -> datetime:
        return self.value


def test_dry_run_then_enforce_removes_out_of_policy(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    backups = tmp_path / "backups"
    report_path = tmp_path / "retention_report.json"
    csv_path = tmp_path / "retention_report.csv"
    artifacts.mkdir()
    backups.mkdir()
    old_file = artifacts / "old.bin"
    old_file.write_bytes(b"x" * 10)
    young_file = artifacts / "young.bin"
    young_file.write_bytes(b"y" * 5)
    big_backup = backups / "big.bin"
    big_backup.write_bytes(b"z" * 20)

    fake_now = FakeNow()
    three_days_ago = fake_now.value - timedelta(days=3)
    os.utime(old_file, (three_days_ago.timestamp(), three_days_ago.timestamp()))

    metrics = ReliabilityMetrics()
    enforcer = RetentionEnforcer(
        artifacts_root=artifacts,
        backups_root=backups,
        config=RetentionConfig(age_days=1, max_total_bytes=20),
        metrics=metrics,
        clock=Clock(ZoneInfo("UTC"), fake_now),
        logger=JSONLogger("test.retention"),
        report_path=report_path,
        csv_report_path=csv_path,
        namespace="retention-tests",
    )

    result = enforcer.run(enforce=True)

    dry = {entry["path"]: entry for entry in result["dry_run"]}
    assert str(old_file) in dry
    assert dry[str(old_file)]["reason"] == "age"

    enforced_paths = {entry["path"] for entry in result["enforced"]}
    assert str(old_file) in enforced_paths
    assert str(big_backup) in enforced_paths
    assert young_file.exists()

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(data["enforced"]) == len(result["enforced"])

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["mode", "path", "reason", "age_days", "size_bytes"]
    assert len(rows) == 1 + len(result["dry_run"]) + len(result["enforced"])
    dry_row = next(row for row in rows if row[0] == "dry_run" and row[2] == "age")
    assert dry_row[3].isdigit()

    dry_age_metric = metrics.retention_actions.labels(
        mode="dry_run", reason="age", namespace="retention-tests"
    )
    dry_size_metric = metrics.retention_actions.labels(
        mode="dry_run", reason="size", namespace="retention-tests"
    )
    enforce_age_metric = metrics.retention_actions.labels(
        mode="enforce", reason="age", namespace="retention-tests"
    )
    enforce_size_metric = metrics.retention_actions.labels(
        mode="enforce", reason="size", namespace="retention-tests"
    )
    assert dry_age_metric._value.get() == 1.0
    assert dry_size_metric._value.get() == 1.0
    assert enforce_age_metric._value.get() == 1.0
    assert enforce_size_metric._value.get() == 1.0

    op_metric = metrics.operations.labels(
        operation="retention",
        outcome="success",
        reason="completed",
        namespace="retention-tests",
    )
    assert op_metric._value.get() == 1.0
