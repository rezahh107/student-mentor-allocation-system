from __future__ import annotations

import time

from sma.ci_orchestrator import orchestrator as orch_mod
from sma.ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_orchestrator_overhead(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)

    def fake_run(cmd, *, capture_output, env, text, check):
        return FakeResult(0)

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(phase="install", install_cmd=("echo", "fast"), retries=1)
    orch = Orchestrator(config)
    start = time.perf_counter()
    orch.run()
    duration = time.perf_counter() - start
    assert duration < 0.2
