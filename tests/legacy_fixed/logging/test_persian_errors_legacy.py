from __future__ import annotations

import json

from sma.ci_orchestrator import orchestrator as orch_mod
from sma.ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_error_envelopes(monkeypatch, tmp_path, capsys):
    _patch_artifacts(monkeypatch, tmp_path)

    def fake_run(cmd, *, capture_output, env, text, check):
        return FakeResult(1)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    orch = Orchestrator(OrchestratorConfig(phase="test", test_cmd=("pytest",), retries=1))
    assert orch.run() == 1
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    error_payload = next(entry for entry in logs if entry.get("event") == "orchestrator.error")
    message = error_payload["message"]
    assert message["کد"] == "WARNINGS_POLICY"
    assert "سیاست هشدار" in message["خطا"]
