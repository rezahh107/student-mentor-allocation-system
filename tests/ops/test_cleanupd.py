from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.reliability import CleanupDaemon, Clock, ReliabilityMetrics
from src.reliability.config import CleanupConfig
from src.reliability.logging_utils import JSONLogger


def test_removes_stale_part_and_expired_links(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    backups = tmp_path / "backups"
    artifacts.mkdir()
    backups.mkdir()
    old_part = artifacts / "sample.part"
    old_part.write_text("temp", encoding="utf-8")
    fresh_part = backups / "fresh.part"
    fresh_part.write_text("keep", encoding="utf-8")

    now = datetime(2024, 5, 1, tzinfo=ZoneInfo("UTC"))
    cutoff = now - timedelta(seconds=120)
    os.utime(old_part, (cutoff.timestamp(), cutoff.timestamp()))

    registry = artifacts / "signed_urls.json"
    registry.write_text(
        json.dumps(
            {
                "expired": {"created_at": (now - timedelta(seconds=3600)).timestamp()},
                "active": {"created_at": (now - timedelta(seconds=10)).timestamp()},
            }
        ),
        encoding="utf-8",
    )

    report_path = tmp_path / "cleanup_report.json"
    metrics = ReliabilityMetrics()
    daemon = CleanupDaemon(
        artifacts_root=artifacts,
        backups_root=backups,
        config=CleanupConfig(part_max_age=60, link_ttl=60),
        metrics=metrics,
        clock=Clock(ZoneInfo("UTC"), lambda: now),
        logger=JSONLogger("test.cleanup"),
        registry_path=registry,
        namespace="cleanup-tests",
        report_path=report_path,
    )

    result = daemon.run()

    assert str(old_part) in result.removed_part_files
    assert fresh_part.exists()

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["namespace"] == "cleanup-tests"
    assert str(old_part) in report_payload["removed_part_files"]

    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    assert "expired" not in registry_payload
    assert "active" in registry_payload

    part_metric = metrics.cleanup_actions.labels(kind="part_file", namespace="cleanup-tests")
    link_metric = metrics.cleanup_actions.labels(kind="signed_url", namespace="cleanup-tests")
    assert part_metric._value.get() == 1.0
    assert link_metric._value.get() == 1.0

    op_metric = metrics.operations.labels(
        operation="cleanup", outcome="success", reason="completed", namespace="cleanup-tests"
    )
    assert op_metric._value.get() == 1.0
