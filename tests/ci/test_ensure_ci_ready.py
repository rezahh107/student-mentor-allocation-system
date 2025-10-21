from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from freezegun import freeze_time

from scripts.ci.ensure_ci_ready import CiReadyGuard, PERSIAN_PYTEST_MISSING
from scripts.deps.ensure_lock import DependencyManager, PERSIAN_LOCK_MISSING


def _prepare_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    (repo / "requirements.in").write_text("fastapi==0.110.3\n", encoding="utf-8")
    (repo / "requirements-dev.in").write_text("-r requirements.in\npytest==8.4.2\n", encoding="utf-8")
    (repo / "constraints.txt").write_text("fastapi==0.110.3\n", encoding="utf-8")
    (repo / "constraints-dev.txt").write_text("pytest==8.4.2\n", encoding="utf-8")
    return repo


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
@freeze_time("2024-05-01T08:15:00+03:30")
def test_ci_ready_guard_success(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    manager = DependencyManager(repo)
    manager._write_metadata()
    manager._write_install_marker(
        constraints=repo / "constraints-dev.txt",
        manifest=repo / "requirements-dev.in",
        attempts=1,
    )

    guard = CiReadyGuard(repo, ["pytest", "pytest_asyncio"], persian=True)
    guard.run()

    metrics = repo / "reports" / "ci-ready.prom"
    assert metrics.exists()
    payload = json.loads((repo / "reports" / "ci-install.json").read_text(encoding="utf-8"))
    assert payload["status"] == "success"


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
@freeze_time("2024-05-01T08:15:00+03:30")
def test_ci_ready_reports_missing_pytest(tmp_path: Path) -> None:
    repo = _prepare_repo(tmp_path)
    manager = DependencyManager(repo)
    manager._write_metadata()
    manager._write_install_marker(
        constraints=repo / "constraints-dev.txt",
        manifest=repo / "requirements-dev.in",
        attempts=1,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.ensure_ci_ready",
            "--root",
            str(repo),
            "--require",
            "pytest",
            "--require",
            "pytest_asyncio_missing_plugin",
            "--persian",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert PERSIAN_PYTEST_MISSING in result.stderr


@pytest.mark.evidence("CI/CD Tailored v2.4 §2")
@freeze_time("2024-05-01T08:15:00+03:30")
def test_ci_ready_rejects_stale_constraints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _prepare_repo(tmp_path)
    manager = DependencyManager(repo)
    manager._write_metadata()
    # Intentionally delete metadata to trigger stale detection
    (repo / ".ci" / "constraints-dev.txt.sha256").unlink()
    manager._write_install_marker(
        constraints=repo / "constraints-dev.txt",
        manifest=repo / "requirements-dev.in",
        attempts=1,
    )

    with pytest.raises(SystemExit) as exc:
        CiReadyGuard(repo, ["pytest"], persian=True).run()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert PERSIAN_LOCK_MISSING in captured.err
