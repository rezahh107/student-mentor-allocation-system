from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.reliability import Clock, DisasterRecoveryDrill, ReliabilityMetrics
from src.reliability.logging_utils import JSONLogger


class FakeNow:
    def __init__(self) -> None:
        self.base = datetime(2024, 3, 1, tzinfo=ZoneInfo("UTC"))
        self.offsets = [0, 5, 10, 15]
        self.index = -1

    def __call__(self) -> datetime:
        self.index += 1
        offset = self.offsets[min(self.index, len(self.offsets) - 1)]
        return self.base + timedelta(seconds=offset)


def test_restore_verifies_sha256_and_records_rto_rpo(tmp_path: Path) -> None:
    source = tmp_path / "src"
    restore = tmp_path / "restore"
    backups = tmp_path / "backups"
    report_path = tmp_path / "dr_report.json"
    source.mkdir()
    backups.mkdir()
    content = "سلام".encode("utf-8")
    (source / "data.txt").write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    metrics = ReliabilityMetrics()
    logger = JSONLogger("test.dr")
    clock = Clock(ZoneInfo("UTC"), FakeNow())
    drill = DisasterRecoveryDrill(
        backups_root=backups,
        metrics=metrics,
        logger=logger,
        clock=clock,
        report_path=report_path,
    )

    report = drill.run(source, restore, correlation_id="cor-1", namespace="drill-tests")

    restored_file = restore / "data.txt"
    assert restored_file.read_bytes() == content

    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["rto_s"] == report["rto_s"]
    assert stored["rpo_s"] == report["rpo_s"]
    assert stored["rto_ms"] == report["rto_ms"]
    assert stored["rpo_ms"] == report["rpo_ms"]
    assert stored["sha256"][0]["sha256"] == expected_sha

    assert report["rto_ms"] >= 0
    assert report["rpo_ms"] >= 0

    success_counter = metrics.dr_runs.labels(status="success", namespace="drill-tests")
    assert success_counter._value.get() == 1.0

    operation_counter = metrics.operations.labels(
        operation="drill", outcome="success", reason="completed", namespace="drill-tests"
    )
    assert operation_counter._value.get() == 1.0

    backup_metric = metrics.dr_bytes.labels(direction="backup", namespace="drill-tests")
    restore_metric = metrics.dr_bytes.labels(direction="restore", namespace="drill-tests")
    assert backup_metric._value.get() == len(content)
    assert restore_metric._value.get() == len(content)
