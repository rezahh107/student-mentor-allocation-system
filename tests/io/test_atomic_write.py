from __future__ import annotations

import os
from pathlib import Path

from src.phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic


def test_atomic_rename_fsync(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "atomic.csv"
    fsync_calls: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    monkeypatch.setattr(os, "fsync", fake_fsync)

    rows = [
        {"name": "دانش‌آموز", "value": "123"},
        {"name": "=cmd", "value": "456"},
    ]

    written = write_csv_atomic(
        destination,
        rows,
        header=["name", "value"],
        sensitive_fields=["value"],
        include_bom=False,
    )

    assert written == destination
    assert destination.exists()
    assert not destination.with_suffix(destination.suffix + ".part").exists()
    assert fsync_calls, "fsync must be invoked for atomic writes"

