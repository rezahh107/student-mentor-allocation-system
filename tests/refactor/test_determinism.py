from __future__ import annotations

from pathlib import Path

from tools.refactor_imports import build_run_id


def test_frozen_time_no_wallclock(tmp_path: Path, clean_state) -> None:
    files = [tmp_path / "a.py", tmp_path / "b.py"]
    for file in files:
        file.write_text("pass\n", encoding="utf-8")
    namespace = "deterministic-test"
    run_one = build_run_id(files, namespace)
    run_two = build_run_id(list(reversed(files)), namespace)
    assert run_one == run_two
    assert len(run_one) == 16
