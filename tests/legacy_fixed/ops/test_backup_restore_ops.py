from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.phase7_release.backup import BackupManager


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_roundtrip_with_hash_check(tmp_path, clean_state):
    clock_now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    manager = BackupManager(clock=lambda: clock_now)
    source_a = tmp_path / "export.csv"
    source_b = tmp_path / "release.json"
    source_a.write_text("data", encoding="utf-8")
    source_b.write_text(json.dumps({"status": "ok"}), encoding="utf-8")

    bundle = manager.backup(sources=[source_a, source_b], destination=tmp_path / "backups")
    restored_dir = tmp_path / "restore"
    restored_dir.mkdir()
    manager.restore(manifest=bundle.manifest, destination=restored_dir)

    assert (restored_dir / "export.csv").read_text("utf-8") == "data"
    assert json.loads((restored_dir / "release.json").read_text("utf-8"))["status"] == "ok"
