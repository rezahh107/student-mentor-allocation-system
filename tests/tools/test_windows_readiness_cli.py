from __future__ import annotations

import io
import json
from pathlib import Path

from typer.testing import CliRunner

from tools.windows_readiness.cli import _update_vscode_tasks, app
from tools.windows_readiness.checks import CheckResult, CheckStatus
from tools.windows_readiness.clock import DeterministicClock
from tools.windows_readiness.logging import JsonLogger
from tools.windows_readiness.report import ArtifactWriter, ReadinessReport


def test_cli_missing_agents(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--path",
            str(tmp_path),
            "--machine",
        ],
    )
    assert result.exit_code == 10
    payload = json.loads(result.stdout.strip())
    assert payload["exit_code"] == 10
    assert payload["status"] == "blocked"
    report_path = tmp_path / "artifacts" / "readiness_report.json"
    assert report_path.exists()


def test_update_vscode_tasks_adds_entry(tmp_path):
    repo_root = tmp_path
    vscode_dir = repo_root / ".vscode"
    vscode_dir.mkdir()
    (vscode_dir / "tasks.json").write_text(json.dumps({"version": "2.0.0", "tasks": []}), encoding="utf-8")
    clock = DeterministicClock("cid")
    logger = JsonLogger(stream=io.StringIO(), clock=clock, correlation_id="cid")
    _update_vscode_tasks(repo_root, logger)
    data = json.loads((vscode_dir / "tasks.json").read_text(encoding="utf-8"))
    labels = [task.get("label") for task in data.get("tasks", [])]
    assert "Windows: Verify & Run" in labels


def test_artifacts_written_with_excel_safety(tmp_path):
    report = ReadinessReport(
        correlation_id="cid",
        repo_root=str(tmp_path),
        remote_expected="https://example.org",
        remote_actual="https://example.org",
        python_required="3.11",
        python_found="3.11.2",
        venv_path=str(tmp_path / ".venv"),
        env_file=str(tmp_path / ".env"),
        port=1234,
        git={"present": True, "ahead": 0, "behind": 0, "dirty": False},
        powershell={"version": "7.4.0", "execution_policy": "Bypass"},
        dependencies_ok=True,
        smoke={"readyz": 200, "metrics": 200, "ui_head": 200},
        status="ready",
        score=100,
        exit_code=0,
        timing_ms=123,
        metrics={"attempts": 1, "retries": 0},
        evidence=["AGENTS.md::Project TL;DR"],
    )
    results = [
        CheckResult(name="agents", status=CheckStatus.PASS, detail="ok", weight=10),
        CheckResult(name="git", status=CheckStatus.PASS, detail="ok", weight=10),
    ]
    writer = ArtifactWriter(tmp_path, jitter=lambda: None)
    writer.write_all(report, results)

    csv_path = tmp_path / "readiness_report.csv"
    data = csv_path.read_bytes()
    assert data.startswith("\ufeff".encode("utf-8"))
    assert b"\r\n" in data

    md_path = tmp_path / "readiness_report.md"
    md_text = md_path.read_bytes()
    assert b"\r\n" in md_text
