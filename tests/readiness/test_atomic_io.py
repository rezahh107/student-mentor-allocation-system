from __future__ import annotations

from pathlib import Path

from ci_orchestrator import orchestrator as orch_mod
from ci_orchestrator.orchestrator import OrchestratorConfig, Orchestrator, atomic_write_text, atomic_write_bytes


def _patch_artifacts(monkeypatch, tmp_path: Path) -> Path:
    art_dir = tmp_path / "artifacts"
    monkeypatch.setattr(orch_mod, "ARTIFACT_DIR", art_dir, raising=False)
    monkeypatch.setattr(orch_mod, "LAST_CMD_ARTIFACT", art_dir / "last_cmd.txt", raising=False)
    monkeypatch.setattr(orch_mod, "WARNINGS_ARTIFACT", art_dir / "ci_warnings_report.json", raising=False)
    return art_dir


def test_atomic_write_and_rename(monkeypatch, tmp_path):
    art_dir = _patch_artifacts(monkeypatch, tmp_path)
    target = art_dir / "sample.txt"
    atomic_write_text(target, "سلام")
    assert target.read_text(encoding="utf-8") == "سلام"
    assert not target.with_suffix(".txt.part").exists()
    atomic_write_bytes(target, b"data")
    assert target.read_bytes() == b"data"


def test_atomic_artifacts_from_orchestrator(monkeypatch, tmp_path, capsys):
    art_dir = _patch_artifacts(monkeypatch, tmp_path)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs["env"]["PYTHONWARNINGS"])
        class Result:
            returncode = 0
            stdout = "== 1 passed, 0 failed, 0 warnings =="
            stderr = ""
        return Result()

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="install", install_cmd=("echo", "hi"), retries=1)
    orchestrator = Orchestrator(config)
    exit_code = orchestrator.run()
    assert exit_code == 0
    assert (art_dir / "last_cmd.txt").read_text() == "echo hi"
    assert (art_dir / "ci_warnings_report.json").exists()
    out = capsys.readouterr().out
    assert "QUALITY ASSESSMENT REPORT" in out
    assert calls == ["default"]
