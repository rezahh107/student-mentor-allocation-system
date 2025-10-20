from __future__ import annotations

from pathlib import Path

from sma.phase2_uploads.storage import AtomicStorage


def test_write_part_fsync_then_rename(tmp_path):
    storage = AtomicStorage(tmp_path)
    writer = storage.writer()
    writer.write(b"data")
    digest = "abcd"
    final_path = storage.finalize(digest, writer)
    assert final_path.exists()
    assert final_path.name == "abcd.csv"
    tmp_dir = tmp_path / "tmp"
    part_files = list(tmp_dir.glob("*.part")) if tmp_dir.exists() else []
    assert not part_files
