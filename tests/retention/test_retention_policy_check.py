from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.phase9_readiness.retention import RetentionPolicy, RetentionValidator
from src.reliability.clock import Clock


def test_retention_fs_timestamp_validation(tmp_path) -> None:
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    now = datetime(2024, 3, 20, 10, tzinfo=ZoneInfo("UTC"))

    newest = backups_root / "backup-new.tar"
    newest.write_bytes(b"n" * 256)

    medium = backups_root / "backup-mid.tar"
    medium.write_bytes(b"m" * (2 * 1024 * 1024))

    old = backups_root / "backup-old.tar"
    old.write_bytes(b"o" * 512)

    def set_times(path, delta_days):
        ts = (now - timedelta(days=delta_days)).timestamp()
        os.utime(path, (ts, ts))

    set_times(newest, 0)
    set_times(medium, 2)
    set_times(old, 30)

    policy = RetentionPolicy(max_age_days=7, max_total_size_mb=1, keep_latest=1, enforce=True)
    clock = Clock(ZoneInfo("Asia/Tehran"), lambda: now)
    validator = RetentionValidator(root=backups_root, clock=clock, policy=policy)

    result = validator.run()
    dry_run = result["dry_run"]
    expired = {item["path"]: item["reasons"] for item in dry_run["expired"]}
    assert str(old) in expired
    assert "age" in expired[str(old)]
    assert str(medium) in expired
    assert "size" in expired[str(medium)]
    retained_paths = {item["path"] for item in dry_run["retained"]}
    assert str(newest) in retained_paths

    enforce = result["enforce"]
    removed_paths = {item["path"] for item in enforce["removed"]}
    assert str(old) in removed_paths
    assert str(medium) in removed_paths
    assert not old.exists()
    assert not medium.exists()
    assert newest.exists()
