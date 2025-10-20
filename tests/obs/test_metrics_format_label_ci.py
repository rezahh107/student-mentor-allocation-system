from __future__ import annotations

import json

from sma.ci_orchestrator import orchestrator as orch_mod
from sma.ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_json_logs_masking(monkeypatch, tmp_path, capsys):
    _patch_artifacts(monkeypatch, tmp_path)

    def fake_run(cmd, *, capture_output, env, text, check):
        return FakeResult(0)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="install", install_cmd=("echo", "user@example.com", "09121234567"), retries=1)
    orchestrator = Orchestrator(config)
    orchestrator.run()
    captured = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert captured, "expected json logs"
    parsed = [json.loads(line) for line in captured]
    for entry in parsed:
        if entry.get("event") == "command.start":
            assert "user@example.com" not in entry["cmd"]
            assert "***@" in entry["cmd"]
            assert "09121234567" not in entry["cmd"]
            assert "09*********" in entry["cmd"]
            break
    else:
        raise AssertionError("command.start log missing")
