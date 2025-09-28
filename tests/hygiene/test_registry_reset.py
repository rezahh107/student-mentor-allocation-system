from __future__ import annotations

from ci_orchestrator import orchestrator as orch_mod
from ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_prom_registry_reset(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)

    def fake_run(cmd, *, capture_output, env, text, check):
        return FakeResult(0)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    first = Orchestrator(OrchestratorConfig(phase="install", install_cmd=("echo", "1"), retries=1))
    first.run()
    second = Orchestrator(OrchestratorConfig(phase="install", install_cmd=("echo", "2"), retries=1))
    assert second._metrics.install_counter._value.get() == 0
    second.run()
    assert second._metrics.install_counter._value.get() == 1
