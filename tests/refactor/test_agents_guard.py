from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tools.refactor_imports import APP


def test_missing_agents_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    result = runner.invoke(APP, ["scan"])
    assert result.exit_code == 1
    output = result.stdout or ""
    assert "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد" in output
