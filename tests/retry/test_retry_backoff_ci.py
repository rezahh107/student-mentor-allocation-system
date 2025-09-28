from __future__ import annotations

from collections import deque

from ci_orchestrator import orchestrator as orch_mod
from ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig

from tests.ci.test_warnings_policy import FakeResult, _patch_artifacts


def test_namespaced_keys(monkeypatch, tmp_path):
    _patch_artifacts(monkeypatch, tmp_path)
    attempts = deque([FakeResult(128), FakeResult(0)])
    envs = []
    sleep_calls = []

    def fake_run(cmd, *, capture_output, env, text, check):
        envs.append(env)
        return attempts.popleft()

    monkeypatch.setattr(orch_mod.subprocess, "run", fake_run)
    config = OrchestratorConfig(
        phase="test",
        test_cmd=("pytest",),
        retries=2,
        sleeper=sleep_calls.append,
    )
    orch = Orchestrator(config)
    orch.run()
    assert len(envs) == 2
    correlation_ids = {env["CORRELATION_ID"] for env in envs}
    assert len(correlation_ids) == 1
    assert envs[0]["PYTHONWARNINGS"] == "error"
    assert sleep_calls, "backoff should be recorded"
    assert orch._metrics.retry_counter._value.get() == 1
