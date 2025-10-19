from __future__ import annotations

from typer.testing import CliRunner

from tools.refactor_imports import APP


def test_persian_error_envelopes(tmp_path, monkeypatch):
    runner = CliRunner()
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (project / "AGENTS.md").write_text("spec", encoding="utf-8")
    monkeypatch.chdir(project)
    result = runner.invoke(APP, ["apply", "--fix-entrypoint", "invalid"])  # invalid format
    assert result.exit_code == 1
    assert "❌ مسیر uvicorn نامعتبر است." in (result.stdout or "")
