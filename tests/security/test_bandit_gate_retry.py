"""Retry and metrics coverage for the Bandit security gate."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from scripts import security_tools
import scripts.run_bandit_gate as bandit_gate


class DeterministicClock:
    def __init__(self) -> None:
        self._value = 10.0

    def __call__(self) -> float:
        self._value += 0.001
        return self._value


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    yield
    security_tools.reset_metrics()


def test_gate_retries_transient_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report_path = reports_dir / "bandit.json"
    alias_path = reports_dir / "bandit-report.json"

    registry = CollectorRegistry()
    monkeypatch.setattr(bandit_gate, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bandit_gate, "REPORT_PATH", report_path)
    monkeypatch.setattr(bandit_gate, "REPORT_ALIAS", alias_path)
    monkeypatch.setattr(bandit_gate, "_RETRY_REGISTRY", registry)
    monkeypatch.setattr(bandit_gate, "_SLEEPER", lambda _: None)
    clock = DeterministicClock()
    monkeypatch.setattr(bandit_gate, "_MONOTONIC", clock)
    monkeypatch.setattr(bandit_gate, "_RANDOMIZER", lambda: 0.0)
    monkeypatch.setenv("SEC_TOOL_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SEC_TOOL_BASE_DELAY", "0")
    monkeypatch.setenv("SEC_TOOL_JITTER", "0")

    attempts: list[int] = []

    def _fake_run() -> subprocess.CompletedProcess[str]:
        attempts.append(1)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, ["bandit"], stderr="transient")
        payload = {"results": [], "errors": []}
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        alias_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(["bandit"], 0, "", "")

    monkeypatch.setattr(bandit_gate, "_run_bandit", _fake_run)

    bandit_gate.main()

    assert len(attempts) == 2, "Bandit gate did not retry exactly once"
    assert report_path.exists() and alias_path.exists()

    attempts_value = registry.get_sample_value(
        "security_tool_retry_attempts_total", labels={"tool": "bandit"}
    )
    assert attempts_value == pytest.approx(2.0)
    exhausted = registry.get_sample_value(
        "security_tool_retry_exhausted_total", labels={"tool": "bandit"}
    )
    assert exhausted in {None, 0.0}
