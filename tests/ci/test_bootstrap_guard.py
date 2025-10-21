from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import bootstrap_guard


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
@pytest.mark.evidence("Tailored v2.4 §2 pip-tools")
def test_bootstrap_guard_installs_minimal_dependencies(tmp_path, monkeypatch, capsys) -> None:
    constraints = tmp_path / "constraints-dev.txt"
    constraints.write_text("pip==24.2\n", encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text("spec", encoding="utf-8")

    recorded: dict[str, object] = {}

    def fake_run(cmd: list[str], *, text: bool, capture_output: bool, env: dict[str, str]):
        recorded["cmd"] = cmd
        recorded["env"] = env
        recorded["called"] = True
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    class StubManager:
        def __init__(self, root: Path, *, correlation_id: str | None = None, metrics_path: Path | None = None) -> None:
            assert recorded.get("called"), "DependencyManager instantiated before bootstrap pip install"
            self.root = root
            self.correlation_id = correlation_id
            self.metrics_path = metrics_path
            self.logs: list[tuple[str, dict[str, object]]] = []

        def log(self, event: str, **fields: object) -> None:
            self.logs.append((event, fields))

        def write_metrics(self) -> None:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            (self.metrics_path).write_text("metrics", encoding="utf-8")

    monkeypatch.setattr(bootstrap_guard, "DependencyManager", StubManager)

    bootstrap_guard.main([
        "--root",
        str(tmp_path),
        "--constraints",
        str(constraints.relative_to(tmp_path)),
    ])

    cmd = recorded.get("cmd")
    assert cmd is not None
    assert "--no-deps" in cmd
    assert "packaging" in cmd
    assert "prometheus-client" in cmd
    assert "tzdata" in cmd
    env = recorded.get("env")
    assert env is not None
    assert env.get("PIP_REQUIRE_HASHES") == ""
    captured = capsys.readouterr().out
    assert "guard_bootstrap_complete" in captured
