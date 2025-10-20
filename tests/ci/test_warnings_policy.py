from __future__ import annotations

from collections import deque
from dataclasses import dataclass


from sma.ci_orchestrator import orchestrator as orch_mod
from sma.ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig


@dataclass
class FakeResult:
    returncode: int
    stdout: str = "== 1 passed, 0 failed, 0 warnings =="
    stderr: str = ""


def _patch_artifacts(monkeypatch, tmp_path):
    art_dir = tmp_path / "artifacts"
    monkeypatch.setattr(orch_mod, "ARTIFACT_DIR", art_dir, raising=False)
    monkeypatch.setattr(orch_mod, "LAST_CMD_ARTIFACT", art_dir / "last_cmd.txt", raising=False)
    monkeypatch.setattr(orch_mod, "WARNINGS_ARTIFACT", art_dir / "ci_warnings_report.json", raising=False)
    return art_dir


def test_install_phase_allows_build_warnings(monkeypatch, tmp_path):
    art_dir = _patch_artifacts(monkeypatch, tmp_path)
    env_calls = []

    def fake_run(cmd, *, capture_output, env, text, check):
        env_calls.append(env["PYTHONWARNINGS"])
        return FakeResult(0, stderr="warning: SetuptoolsDeprecationWarning")

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="install", install_cmd=("echo", "install"), retries=1)
    orch = Orchestrator(config)
    assert orch.run() == 0
    assert env_calls == ["default"]
    assert (art_dir / "ci_warnings_report.json").exists()


def test_test_phase_enforces_error(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)

    def fake_run(*args, **kwargs):
        return FakeResult(1, stdout="== 1 failed, 0 passed ==", stderr="warning: Something")

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="test", test_cmd=("pytest",), retries=1)
    orch = Orchestrator(config)
    assert orch.run() == 1


def test_all_runs_both(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)
    calls = deque([FakeResult(0), FakeResult(0)])
    env_values = []

    def fake_run(cmd, *, capture_output, env, text, check):
        env_values.append(env["PYTHONWARNINGS"])
        return calls.popleft()

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="all", install_cmd=("echo", "install"), test_cmd=("pytest",), retries=1)
    orch = Orchestrator(config)
    assert orch.run() == 0
    assert env_values == ["default", "error"]


def test_allows_pytest_args_sanitization(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)
    received = {}

    def fake_run(cmd, *, capture_output, env, text, check):
        received["cmd"] = cmd
        return FakeResult(0)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    dirty_arg = "--cov=app\x07"
    config = OrchestratorConfig(phase="test", test_cmd=("pytest",), pytest_args=(dirty_arg,), retries=1)
    orch = Orchestrator(config)
    orch.run()
    assert received["cmd"] == ("pytest", "--cov=app")
