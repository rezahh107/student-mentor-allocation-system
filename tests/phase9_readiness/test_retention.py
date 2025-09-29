from __future__ import annotations

import json
import os
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from src.phase9_readiness.retention import RetentionPolicy, RetentionValidator


@pytest.mark.usefixtures("frozen_time")
def test_retention_policy_check(orchestrator, clean_state, tmp_path, clock):
    source = tmp_path / "data.txt"
    source.write_text("x" * 128, encoding="utf-8")

    def create_backup() -> Path:
        target = clean_state["reports"] / "retained.tar"
        target.write_bytes(source.read_bytes())
        return target

    def restore_backup(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        return {"checksum": sha256(data).hexdigest(), "restored": True}

    legacy = clean_state["reports"] / "legacy.tar"
    legacy.write_text("legacy", encoding="utf-8")
    old_time = clock.now() - timedelta(days=30)
    ts = old_time.timestamp()
    os.utime(legacy, (ts, ts))

    policy = RetentionPolicy(max_age_days=7, max_total_size_mb=8, keep_latest=1, enforce=False)
    validator = RetentionValidator(root=clean_state["reports"], clock=clock, policy=policy)

    orchestrator.verify_backup_restore(
        create_backup=create_backup,
        restore_backup=restore_backup,
        retention_validator=validator,
        correlation_id="rid-phase9-retention",
    )
    payload = json.loads((clean_state["reports"] / "backup_restore_report.json").read_text(encoding="utf-8"))
    expired_paths = {Path(item["path"]).name for item in payload["retention"]["dry_run"]["expired"]}
    assert "legacy.tar" in expired_paths
