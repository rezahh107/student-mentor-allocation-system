from __future__ import annotations

from pathlib import Path

from tools.uvicorn_entrypoint_guard import patch_files


def test_ps1_bat_sh_variants(tmp_path: Path) -> None:
    ps1 = tmp_path / "launch.ps1"
    ps1.write_text("uvicorn 'app.main:run' --reload\n", encoding="utf-8")
    bat = tmp_path / "launch.bat"
    bat.write_text("uvicorn.exe app.main:run --host 0.0.0.0\r\n", encoding="utf-8")
    sh = tmp_path / "launch.sh"
    sh.write_text("#!/bin/sh\nuvicorn app.main:run --factory\n", encoding="utf-8")

    results = list(patch_files([ps1, bat, sh], "src.main:app"))

    assert all(result.changed for result in results)
    assert "src.main:app" in ps1.read_text(encoding="utf-8")
    assert "src.main:app" in bat.read_text(encoding="utf-8")
    assert "src.main:app" in sh.read_text(encoding="utf-8")
