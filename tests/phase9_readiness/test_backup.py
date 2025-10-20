from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from sma.phase9_readiness.retention import RetentionPolicy, RetentionValidator


@pytest.mark.usefixtures("frozen_time")
def test_restore_with_hash_verify(orchestrator, clean_state, metrics, tmp_path, clock):
    payload = tmp_path / "payload.bin"
    payload.write_text("داده تستی" * 8, encoding="utf-8")

    def create_backup() -> Path:
        archive = clean_state["reports"] / "backup.tar"
        archive.write_bytes(payload.read_bytes())
        return archive

    def restore_backup(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        digest = sha256(data).hexdigest()
        restored = tmp_path / "restore" / path.name
        restored.parent.mkdir(parents=True, exist_ok=True)
        restored.write_bytes(data)
        return {"checksum": digest, "restored": True, "bytes": len(data)}

    policy = RetentionPolicy(max_age_days=30, max_total_size_mb=16, keep_latest=1, enforce=False)
    validator = RetentionValidator(root=clean_state["reports"], clock=clock, policy=policy)

    payload = orchestrator.verify_backup_restore(
        create_backup=create_backup,
        restore_backup=restore_backup,
        retention_validator=validator,
        correlation_id="rid-phase9-backup",
    )
    report_path = clean_state["reports"] / "backup_restore_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["checksum"] == payload["checksum"]
    assert report["restore"]["restored"] is True
    assert report["retention"]["policy"]["max_age_days"] == 30
    dry_run_retained = {Path(item["path"]).name for item in report["retention"]["dry_run"]["retained"]}
    assert "backup.tar" in dry_run_retained

    samples = metrics.backup_restore_runs.collect()[0].samples
    outcomes = {(s.labels["stage"], s.labels["outcome"]) for s in samples}
    assert ("backup", "success") in outcomes
    assert ("restore", "success") in outcomes
    assert ("retention", "success") in outcomes

    duration_labels = {sample.labels["stage"] for sample in metrics.stage_duration.collect()[0].samples}
    assert {"backup.create", "backup.restore", "backup.retention"}.issubset(duration_labels)
