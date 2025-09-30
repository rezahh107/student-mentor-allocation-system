from __future__ import annotations

import os

import pytest

from src.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from src.phase6_import_to_sabt.xlsx.utils import atomic_write

_ANCHOR = "AGENTS.md::Atomic I/O & Excel-Safety"


def test_part_rename_fsync(cleanup_fixtures, monkeypatch) -> None:
    output_dir = cleanup_fixtures.base_dir / "atomic"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "export.bin"
    metrics = build_import_export_metrics(cleanup_fixtures.registry)

    fsync_calls: list[int] = []
    original_fsync = os.fsync

    def capture_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        original_fsync(fd)

    monkeypatch.setattr("src.phase6_import_to_sabt.xlsx.utils.os.fsync", capture_fsync)

    with atomic_write(
        target,
        metrics=metrics,
        format_label="xlsx",
        sleeper=lambda _: None,
    ) as handle:
        handle.write(b"data")

    debug_context = cleanup_fixtures.context(target=str(target), evidence=_ANCHOR)
    assert target.exists(), debug_context
    assert fsync_calls, {"debug": debug_context, "fsync_calls": fsync_calls}
    assert not list(output_dir.glob("*.part")), debug_context
    assert target.read_bytes() == b"data", debug_context

    failing_target = output_dir / "error.bin"
    error_context = cleanup_fixtures.context(target=str(failing_target), evidence=_ANCHOR)
    with pytest.raises(RuntimeError):
        with atomic_write(
            failing_target,
            metrics=metrics,
            format_label="xlsx",
            sleeper=lambda _: None,
        ) as handle:
            handle.write(b"payload")
            raise RuntimeError("forced failure")
    assert not failing_target.exists(), error_context
    assert not list(output_dir.glob("error.bin.part")), error_context
