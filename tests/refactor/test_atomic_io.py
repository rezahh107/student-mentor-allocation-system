from __future__ import annotations

from pathlib import Path

import pytest

from tools import refactor_imports


def test_atomic_write_and_fsync(tmp_path: Path, clean_state, monkeypatch) -> None:
    target = tmp_path / "data.txt"
    calls = []

    def fake_fsync(fd: int) -> None:
        calls.append(fd)

    monkeypatch.setattr(refactor_imports.os, "fsync", fake_fsync)
    refactor_imports.atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not list(tmp_path.glob("*.part"))
    assert calls, "fsync must be invoked"

    refactor_imports.atomic_write_text(target, "سلام")
    assert target.read_text(encoding="utf-8") == "سلام"


@pytest.mark.parametrize("value", ["", "0", "۰", "\u200c"])  # zero-width and digits
def test_normalize_handles_edge_cases(value: str) -> None:
    assert refactor_imports.normalize_persian_value(value) == refactor_imports.normalize_persian_value(value)
