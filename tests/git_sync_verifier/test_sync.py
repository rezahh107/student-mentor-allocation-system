from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_sync_verifier.cli import app
from git_sync_verifier import git_ops
from git_sync_verifier.core import SyncOptions, run
from git_sync_verifier.exceptions import GitCommandError
from git_sync_verifier.metrics import SyncMetrics


runner = CliRunner()


def test_in_sync_generates_artifacts(repo_factory, stub_clock, sync_metrics: SyncMetrics, tmp_path: Path) -> None:
    repo = repo_factory()
    out_dir = tmp_path / "out"
    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=out_dir,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)

    assert outcome.exit_code == 0
    assert outcome.status == "in_sync"
    assert outcome.report["metrics"]["fetch_attempts"] == 1
    assert outcome.report["middleware_trace"] == ["RateLimit", "Idempotency", "Auth"]

    json_path = out_dir / "sync_report.json"
    csv_path = out_dir / "sync_report.csv"
    md_path = out_dir / "sync_report.md"
    assert json_path.exists()
    assert csv_path.exists()
    assert md_path.exists()

    json_bytes = json_path.read_bytes()
    assert b"\r\n" in json_bytes

    csv_bytes = csv_path.read_bytes()
    assert csv_bytes.startswith("\ufeff".encode("utf-8"))
    assert b"\r\n" in csv_bytes
    assert b"," in csv_bytes

    md_content = md_path.read_text(encoding="utf-8")
    assert "گزارش" in md_content


def test_dirty_repo_exit_5(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    (repo.worktree / "README.md").write_text("dirty\n", encoding="utf-8")

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 5
    assert outcome.status == "dirty"


def test_ahead_exit_3(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    (repo.worktree / "ahead.txt").write_text("ahead\n", encoding="utf-8")
    _run_git(["git", "add", "ahead.txt"], repo.worktree)
    _run_git(["git", "commit", "-m", "ahead"], repo.worktree)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 3
    assert outcome.status == "ahead"


def test_behind_exit_2(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    other = repo.worktree.parent / "other"
    _run_git(["git", "clone", repo.remote_uri, other.name], repo.worktree.parent)
    _run_git(["git", "config", "user.name", "other"], other)
    _run_git(["git", "config", "user.email", "other@example.com"], other)
    (other / "new.txt").write_text("remote\n", encoding="utf-8")
    _run_git(["git", "add", "new.txt"], other)
    _run_git(["git", "commit", "-m", "remote"], other)
    _run_git(["git", "push", "origin", "HEAD:main"], other)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 2
    assert outcome.status == "behind"


def test_diverged_exit_4(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    # Local ahead
    (repo.worktree / "ahead.txt").write_text("ahead\n", encoding="utf-8")
    _run_git(["git", "add", "ahead.txt"], repo.worktree)
    _run_git(["git", "commit", "-m", "ahead"], repo.worktree)
    # Remote advanced separately
    other = repo.worktree.parent / "other2"
    _run_git(["git", "clone", repo.remote_uri, other.name], repo.worktree.parent)
    _run_git(["git", "config", "user.name", "other2"], other)
    _run_git(["git", "config", "user.email", "other2@example.com"], other)
    (other / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run_git(["git", "add", "remote.txt"], other)
    _run_git(["git", "commit", "-m", "remote"], other)
    _run_git(["git", "push", "origin", "HEAD:main"], other)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 4
    assert outcome.status == "diverged"


def test_remote_mismatch_exit_6(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    _run_git(["git", "remote", "set-url", "origin", "https://example.com/other.git"], repo.worktree)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 6
    assert outcome.status == "remote_mismatch"
    assert outcome.report["remote_actual"] == "https://example.com/other.git"


def test_shallow_repo_exit_8(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    shallow_dir = repo.worktree.parent / "shallow"
    _run_git(["git", "clone", "--depth", "1", repo.remote_uri, shallow_dir.name], repo.worktree.parent)
    _run_git(["git", "config", "user.name", "shallow"], shallow_dir)
    _run_git(["git", "config", "user.email", "shallow@example.com"], shallow_dir)
    _run_git(
        ["git", "remote", "set-url", "origin", "https://github.com/rezahh107/student-mentor-allocation-system.git"],
        shallow_dir,
    )
    _run_git(["git", "config", f"url.{repo.remote_uri}.insteadOf", "https://github.com/rezahh107/student-mentor-allocation-system"], shallow_dir)
    _run_git(["git", "config", f"url.{repo.remote_uri}.insteadOf", "https://github.com/rezahh107/student-mentor-allocation-system.git"], shallow_dir)

    options = SyncOptions(
        path=shallow_dir,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 8
    assert outcome.status == "shallow_or_detached"


def test_missing_agents_exit_10(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    (repo.worktree / "AGENTS.md").unlink()

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 10
    assert outcome.status == "error"
    assert "AGENTS" in outcome.report["error"]


def test_concurrent_lock(repo_factory, stub_clock, tmp_path) -> None:
    repo = repo_factory()
    metrics_one = SyncMetrics()
    metrics_two = SyncMetrics()
    out_one = tmp_path / "one"
    out_two = tmp_path / "two"

    options_one = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=out_one,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )
    options_two = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=out_two,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    results: list[int] = []

    def worker(opts, metrics):
        outcome = run(opts, clock=stub_clock, metrics=metrics)
        results.append(outcome.exit_code)

    thread_one = threading.Thread(target=worker, args=(options_one, metrics_one))
    thread_two = threading.Thread(target=worker, args=(options_two, metrics_two))
    thread_one.start()
    thread_two.start()
    thread_one.join()
    thread_two.join()

    assert results.count(0) == 2


def test_machine_flag_outputs_json(repo_factory, monkeypatch):
    repo = repo_factory()

    fake_report = {
        "correlation_id": "cid",
        "status": "in_sync",
        "exit_code": 0,
        "path": str(repo.worktree),
        "metrics": {"fetch_attempts": 1, "retries": 0},
    }

    class FakeOutcome:
        exit_code = 0
        status = "in_sync"
        message = "ok"
        report = fake_report

    monkeypatch.setattr("git_sync_verifier.cli.run", lambda options: FakeOutcome())
    result = runner.invoke(
        app,
        [
            "--path",
            str(repo.worktree),
            "--machine",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == fake_report


def test_submodule_drift_exit_7(repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    sub_repo = repo.worktree.parent / "sub"
    sub_repo.mkdir()
    _run_git(["git", "init"], sub_repo)
    _run_git(["git", "config", "user.name", "sub"], sub_repo)
    _run_git(["git", "config", "user.email", "sub@example.com"], sub_repo)
    (sub_repo / "data.txt").write_text("v1\n", encoding="utf-8")
    _run_git(["git", "add", "data.txt"], sub_repo)
    _run_git(["git", "commit", "-m", "init sub"], sub_repo)

    _run_git(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            sub_repo.resolve().as_uri(),
            "modules/sub",
        ],
        repo.worktree,
    )
    _run_git(["git", "commit", "-am", "add submodule"], repo.worktree)
    _run_git(["git", "push", "origin", "HEAD:main"], repo.worktree)

    sub_worktree = repo.worktree / "modules" / "sub"
    (sub_worktree / "data.txt").write_text("v2\n", encoding="utf-8")
    _run_git(["git", "add", "data.txt"], sub_worktree)
    _run_git(["git", "commit", "-m", "advance sub"], sub_worktree)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 7
    assert outcome.status == "submodule_drift"
    assert any(item["status"] != "ok" for item in outcome.report["submodules"])


def test_lfs_pointer_mismatch_exit_7(monkeypatch, repo_factory, stub_clock, sync_metrics: SyncMetrics) -> None:
    repo = repo_factory()
    (repo.worktree / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    _run_git(["git", "add", ".gitattributes"], repo.worktree)
    _run_git(["git", "commit", "-m", "add lfs config"], repo.worktree)
    _run_git(["git", "push", "origin", "HEAD:main"], repo.worktree)

    original_run_git = git_ops.run_git

    def fake_run_git(args, repo_path, timeout):
        if args[:3] == ["git", "lfs", "ls-files"]:
            raise GitCommandError(args, 1, "lfs missing")
        return original_run_git(args, repo_path, timeout)

    monkeypatch.setattr("git_sync_verifier.git_ops.run_git", fake_run_git)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    assert outcome.exit_code == 7
    assert outcome.status == "submodule_drift"
    assert outcome.report["lfs"]["pointer_mismatches"] >= 1


def test_fetch_retry_records_metrics(monkeypatch, repo_factory, stub_clock) -> None:
    repo = repo_factory()
    metrics = SyncMetrics()
    original_run_git = git_ops.run_git
    attempts = {"count": 0}

    def fake_run_git(args, repo_path, timeout):
        if args[:3] == ["git", "fetch", "--tags"]:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise GitCommandError(args, 1, "network fail")
        return original_run_git(args, repo_path, timeout)

    monkeypatch.setattr("git_sync_verifier.git_ops.run_git", fake_run_git)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=metrics)
    assert outcome.exit_code == 0
    assert outcome.report["metrics"]["fetch_attempts"] == 2
    assert outcome.report["metrics"]["retries"] == 1


def test_fetch_failure_exit_9(monkeypatch, repo_factory, stub_clock) -> None:
    repo = repo_factory()
    metrics = SyncMetrics()
    original_run_git = git_ops.run_git

    def fake_run_git(args, repo_path, timeout):
        if args[:3] == ["git", "fetch", "--tags"]:
            raise GitCommandError(args, 1, "down")
        return original_run_git(args, repo_path, timeout)

    monkeypatch.setattr("git_sync_verifier.git_ops.run_git", fake_run_git)

    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=None,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )

    outcome = run(options, clock=stub_clock, metrics=metrics)
    assert outcome.exit_code == 9
    assert outcome.status == "error"
    assert "fetch" in outcome.report["error"]


def test_csv_formula_guard(repo_factory, stub_clock, sync_metrics: SyncMetrics, tmp_path, monkeypatch) -> None:
    repo = repo_factory()
    out_dir = tmp_path / "=danger"
    monkeypatch.setenv("CORRELATION_ID", "=test")
    options = SyncOptions(
        path=repo.worktree,
        remote="https://github.com/rezahh107/student-mentor-allocation-system.git",
        branch=None,
        timeout=5,
        out_dir=out_dir,
        machine=False,
        fix_remote=False,
        confirm_fix=False,
        fix_submodules=False,
    )
    outcome = run(options, clock=stub_clock, metrics=sync_metrics)
    csv_path = out_dir / "sync_report.csv"
    content = csv_path.read_text(encoding="utf-8-sig")
    first_row = content.splitlines()[1]
    assert "'=test" in first_row
    monkeypatch.delenv("CORRELATION_ID", raising=False)


def _run_git(args: list[str], cwd: Path) -> None:
    completed = __import__("subprocess").run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(args)} -> {completed.stderr}")
