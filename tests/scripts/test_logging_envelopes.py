from __future__ import annotations

import os
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.logging_asserts import assert_log_envelope, parse_json_lines


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_verify_agents_outputs_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ | {"SMA_CORRELATION_ID": "verify-ci"}
    proc = subprocess.run(
        ["python", "scripts/verify_agents.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    logs = parse_json_lines(proc.stdout)
    assert logs, "no logs from verify_agents"
    payload = logs[-1]
    assert_log_envelope(payload, expected_event="agents_verified")
    evidence = payload.get("evidence", [])
    assert "AGENTS.md::1 Determinism" in evidence
    assert "AGENTS.md::3 Absolute Guardrails" in evidence
    assert "AGENTS.md::8 Testing & CI Gates" in evidence


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_rewrite_imports_emits_json() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ | {"SMA_CORRELATION_ID": "rewrite-test"}
    proc = subprocess.run(
        ["python", "tools/rewrite_imports.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    logs = parse_json_lines(proc.stdout)
    assert logs, f"expected logs from rewrite_imports: {proc.stdout}"
    assert_log_envelope(logs[-1])


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_migrate_shadowing_emits_json(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    tools_dir = repo_dir / "tools"
    src_dir = repo_dir / "src"
    tools_dir.mkdir(parents=True)
    src_dir.mkdir(parents=True)
    (src_dir / "fastapi").mkdir()
    (src_dir / "project").mkdir()
    script_path = Path(__file__).resolve().parents[2] / "tools" / "migrate_shadowing.sh"
    shutil.copy(script_path, tools_dir / "migrate_shadowing.sh")
    env = os.environ | {"CORRELATION_ID": "migration-test"}
    proc = subprocess.run(
        ["bash", "tools/migrate_shadowing.sh"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    logs = parse_json_lines(proc.stdout)
    assert logs, proc.stdout
    assert_log_envelope(logs[0], expected_event="migration_start")
    assert any(entry.get("event") == "migration_complete" for entry in logs)


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_guard_pythonpath_passes_without_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ | {"SMA_CORRELATION_ID": "pythonpath-pass", "PYTHONPATH": ""}
    proc = subprocess.run(
        ["python", "scripts/guard_pythonpath.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    logs = parse_json_lines(proc.stdout)
    assert logs, "expected guard_pythonpath output"
    assert_log_envelope(logs[-1], expected_event="pythonpath_guard")
    assert logs[-1]["correlation_id"] == "pythonpath-pass"


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_guard_pythonpath_blocks_front_loading() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ | {
        "SMA_CORRELATION_ID": "pythonpath-fail",
        "PYTHONPATH": f"{repo_root / 'src'}{os.pathsep}/usr/lib/python3.11/site-packages",
    }
    proc = subprocess.run(
        ["python", "scripts/guard_pythonpath.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 1, proc.stdout
    logs = parse_json_lines(proc.stderr)
    assert logs, proc.stderr
    payload = logs[-1]
    assert_log_envelope(payload, expected_event="pythonpath_violation")
    assert payload["correlation_id"] == "pythonpath-fail"
    assert payload.get("details", {}).get("reason") in {"repo-root", "src-before-site"}
