from __future__ import annotations

from sma.ci_orchestrator import orchestrator as orch_mod
from sma.ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_retry_exhaustion_counters(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)
    monkeypatch.setattr(orch_mod.MetricsServer, "start", lambda self: None)
    calls = [
        FakeResult(0, stdout="== 1 passed, 0 failed, 0 warnings =="),
        FakeResult(0, stdout="== 1 passed, 0 failed, 0 skipped, 2 warnings =="),
    ]

    def fake_run(cmd, *, capture_output, env, text, check):
        return calls.pop(0)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(
        phase="all",
        install_cmd=("echo", "install"),
        test_cmd=("pytest",),
        retries=1,
        metrics_enabled=True,
        metrics_token="token",
    )
    orchestrator = Orchestrator(config)
    orchestrator.run()
    assert orchestrator._metrics.retry_exhausted_counter._value.get() == 2
    assert orchestrator._metrics.test_counter._value.get() == 1
