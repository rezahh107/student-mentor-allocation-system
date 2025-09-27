from __future__ import annotations

import os

import pytest

from src.phase7_release.backup import BackupManager


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_prunes_old_artifacts(tmp_path, clean_state):
    manager = BackupManager(clock=lambda: tmp_path.stat().st_mtime)
    root = tmp_path / "snapshots"
    root.mkdir()
    for index in range(5):
        snapshot = root / f"20240101T00000{index}Z"
        snapshot.mkdir()
        data = snapshot / "data.bin"
        data.write_bytes(os.urandom(4))
    manager.apply_retention(root=root, max_items=2, max_total_bytes=16)
    remaining = sorted(path.name for path in root.iterdir())
    assert len(remaining) <= 2
