from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from git_sync_verifier.clock import Clock, DEFAULT_TZ
from git_sync_verifier.core import DEFAULT_REMOTE
from git_sync_verifier.metrics import SyncMetrics


@dataclass
class RepoHandle:
    worktree: Path
    remote_uri: str
    bare: Path


@pytest.fixture
def stub_clock() -> Clock:
    base_epoch = 1_700_000_000.0
    monotonic_state = {"value": 10.0}

    def time_fn() -> float:
        return base_epoch

    def monotonic_fn() -> float:
        monotonic_state["value"] += 0.1
        return monotonic_state["value"]

    return Clock(time_fn=time_fn, monotonic_fn=monotonic_fn, timezone=DEFAULT_TZ)


@pytest.fixture
def sync_metrics() -> SyncMetrics:
    return SyncMetrics()


@pytest.fixture
def repo_factory(tmp_path_factory: pytest.TempPathFactory) -> Callable[[], RepoHandle]:
    root = Path(__file__).resolve().parents[2]
    agents_source = root / "AGENTS.md"

    def _factory() -> RepoHandle:
        base = tmp_path_factory.mktemp("repo")
        remote_bare = base / "remote.git"
        worktree = base / "work"
        _run(["git", "init", "--bare", remote_bare.name], cwd=base)
        remote_uri = (base / remote_bare.name).resolve().as_uri()
        _run(["git", "clone", remote_uri, worktree.name], cwd=base)
        _run(["git", "config", "user.name", "tester"], cwd=worktree)
        _run(["git", "config", "user.email", "tester@example.com"], cwd=worktree)

        (worktree / "README.md").write_text("seed\n", encoding="utf-8")
        shutil.copyfile(agents_source, worktree / "AGENTS.md")
        _run(["git", "add", "README.md", "AGENTS.md"], cwd=worktree)
        _run(["git", "commit", "-m", "seed"], cwd=worktree)
        _run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=worktree)
        _run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote_bare)
        _run(["git", "remote", "set-head", "origin", "main"], cwd=worktree)

        _run(["git", "remote", "set-url", "origin", DEFAULT_REMOTE], cwd=worktree)
        remote_alias = remote_uri.removesuffix(".git")
        _run(["git", "config", f"url.{remote_alias}.insteadOf", DEFAULT_REMOTE], cwd=worktree)
        _run(
            ["git", "config", f"url.{remote_alias}.insteadOf", DEFAULT_REMOTE.removesuffix(".git")],
            cwd=worktree,
        )

        return RepoHandle(worktree=worktree, remote_uri=remote_uri, bare=remote_bare)

    return _factory


def _run(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)} -> {completed.stderr}")
