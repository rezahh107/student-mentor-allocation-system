"""Git command helpers for sync verifier."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Iterable

from .clock import Clock
from .exceptions import GitCommandError
from .logging_utils import mask_path
from .middleware import FetchContext, FetchResult, build_default_chain


def run_git(
    args: list[str],
    repo_path: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Execute git command and capture output."""
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    try:
        completed = subprocess.run(
            args,
            cwd=repo_path,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:  # git missing
        raise GitCommandError(args, returncode=127, stderr=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError(args, returncode=124, stderr=str(exc)) from exc

    if completed.returncode != 0:
        raise GitCommandError(args, completed.returncode, completed.stderr.strip())
    return completed


def fetch_with_retry(
    repo_path: Path,
    remote: str,
    remote_url: str,
    timeout: int,
    *,
    max_attempts: int,
    base_delay_ms: int,
    clock: Clock,
    logger,
    metrics,
    correlation_id: str,
) -> tuple[FetchResult, int, int, list[str]]:
    """Run git fetch with middleware pipeline and retry strategy."""
    ctx = FetchContext(
        repo_path=repo_path,
        remote=remote,
        remote_url=remote_url,
        timeout=timeout,
        correlation_id=correlation_id,
        logger=logger,
        clock=clock,
        metrics=metrics,
    )

    def _final_callable(final_ctx: FetchContext) -> FetchResult:
        final_ctx.fetch_attempts += 1
        args = ["git", "fetch", "--tags", "--prune", final_ctx.remote]
        completed = run_git(args, repo_path, timeout)
        return FetchResult(success=True, return_code=completed.returncode)

    chain = build_default_chain(_final_callable)
    last_error: GitCommandError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = chain.execute(ctx)
            return result, ctx.fetch_attempts, ctx.fetch_retries, list(ctx.middleware_trace)
        except GitCommandError as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            ctx.fetch_retries += 1
            wait_ms = _calculate_backoff_ms(
                correlation_id=correlation_id,
                masked_path=mask_path(repo_path),
                attempt=attempt,
                base_delay_ms=base_delay_ms,
            )
            logger.warning(
                "git_fetch_retry",
                extra={
                    "correlation_id": correlation_id,
                    "attempt": attempt,
                    "wait_ms": wait_ms,
                    "returncode": exc.returncode,
                },
            )
    if last_error is not None:
        return (
            FetchResult(success=False, return_code=last_error.returncode, stderr=last_error.stderr),
            ctx.fetch_attempts,
            ctx.fetch_retries,
            list(ctx.middleware_trace),
        )
    return (
        FetchResult(success=False, return_code=None, stderr=None),
        ctx.fetch_attempts,
        ctx.fetch_retries,
        list(ctx.middleware_trace),
    )


def _calculate_backoff_ms(
    *,
    correlation_id: str,
    masked_path: str,
    attempt: int,
    base_delay_ms: int,
) -> int:
    exponent = attempt - 1
    deterministic_part = base_delay_ms * (2**exponent)
    seed = f"{correlation_id}:{masked_path}:{attempt}".encode("utf-8")
    digest = hashlib.blake2b(seed, digest_size=4).digest()
    jitter = int.from_bytes(digest, "big") % base_delay_ms
    return deterministic_part + jitter


def get_repo_root(path: Path, timeout: int) -> Path:
    """Return git repo root."""
    completed = run_git(["git", "rev-parse", "--show-toplevel"], path, timeout)
    return Path(completed.stdout.strip())


def get_remote_url(repo_path: Path, timeout: int) -> str:
    """Return origin remote URL."""
    completed = run_git(["git", "remote", "get-url", "origin"], repo_path, timeout)
    return completed.stdout.strip()


def get_default_branch(repo_path: Path, timeout: int) -> str:
    """Resolve default branch from origin/HEAD."""
    try:
        completed = run_git(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            repo_path,
            timeout,
        )
        ref = completed.stdout.strip()
        if ref.startswith("refs/remotes/origin/"):
            return ref.removeprefix("refs/remotes/origin/")
    except GitCommandError:
        show = run_git(["git", "remote", "show", "origin"], repo_path, timeout)
        for line in show.stdout.splitlines():
            line = line.strip()
            if line.lower().startswith("head branch:"):
                branch = line.split(":", 1)[1].strip()
                if branch:
                    return branch
    raise GitCommandError(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], 1, "invalid ref")


def get_head_commit(repo_path: Path, timeout: int) -> str:
    """Return local HEAD commit sha1."""
    completed = run_git(["git", "rev-parse", "HEAD"], repo_path, timeout)
    return completed.stdout.strip()


def get_ref_commit(repo_path: Path, ref: str, timeout: int) -> str:
    """Return commit for ref."""
    completed = run_git(["git", "rev-parse", ref], repo_path, timeout)
    return completed.stdout.strip()


def get_ahead_behind(repo_path: Path, branch: str, timeout: int) -> tuple[int, int]:
    """Return ahead, behind counts relative to origin/branch."""
    ref = f"origin/{branch}"
    completed = run_git(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{ref}"],
        repo_path,
        timeout,
    )
    raw = completed.stdout.strip().split()
    if len(raw) != 2:
        raise GitCommandError(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...{ref}"],
            1,
            "unexpected rev-list output",
        )
    ahead = int(raw[0])
    behind = int(raw[1])
    return ahead, behind


def get_status_porcelain(repo_path: Path, timeout: int) -> list[str]:
    """Return porcelain status lines."""
    completed = run_git(["git", "status", "--porcelain=v1"], repo_path, timeout)
    lines = [line for line in completed.stdout.splitlines() if line]
    return lines


def count_untracked(lines: Iterable[str]) -> int:
    """Count untracked entries in status output."""
    return sum(1 for line in lines if line.startswith("??"))


def has_dirty_changes(lines: Iterable[str], *, submodule_paths: set[str] | None = None) -> bool:
    """Return True if repo has dirty changes."""
    submodule_paths = submodule_paths or set()
    for line in lines:
        if line.startswith("??"):
            path = line[3:].strip()
            if path in submodule_paths:
                continue
            return True
        staged = line[0]
        unstaged = line[1]
        if staged.strip() or unstaged.strip():
            path = line[3:].split(" -> ", 1)[0].strip()
            if path in submodule_paths and staged == " " and unstaged == "M":
                continue
            return True
    return False


def tags_aligned(repo_path: Path, timeout: int) -> bool:
    """Verify local and remote tags alignment."""
    local_refs = run_git(
        ["git", "for-each-ref", "refs/tags", "--format", "%(refname:strip=2) %(objectname)"],
        repo_path,
        timeout,
    ).stdout.strip().splitlines()
    remote_refs = run_git(["git", "ls-remote", "--tags", "origin"], repo_path, timeout).stdout.strip()
    remote_lines = [line for line in remote_refs.splitlines() if line and not line.endswith("^{}")]

    local_map = dict(line.split(" ", 1) for line in local_refs if " " in line)
    remote_map = {}
    for line in remote_lines:
        sha, ref = line.split("\t", 1)
        name = ref.removeprefix("refs/tags/")
        remote_map[name] = sha
    return local_map == remote_map


def is_shallow(repo_path: Path, timeout: int) -> bool:
    """Check if repository is shallow."""
    completed = run_git(["git", "rev-parse", "--is-shallow-repository"], repo_path, timeout)
    return completed.stdout.strip().lower() == "true"


def is_detached(repo_path: Path, timeout: int) -> bool:
    """Check if HEAD is detached."""
    try:
        run_git(["git", "symbolic-ref", "--quiet", "HEAD"], repo_path, timeout)
    except GitCommandError:
        return True
    return False


def list_submodules(
    repo_path: Path,
    branch: str,
    timeout: int,
) -> list[dict[str, str]]:
    """Inspect submodules and detect drift."""
    gitmodules = repo_path / ".gitmodules"
    if not gitmodules.exists():
        return []

    completed = run_git(["git", "submodule", "status", "--recursive"], repo_path, timeout)
    lines = completed.stdout.strip().splitlines()
    submodules: list[dict[str, str]] = []
    for line in lines:
        if not line:
            continue
        status_char = line[0]
        parts = line[1:].strip().split(" ", 1)
        if not parts:
            continue
        commit_local = parts[0]
        remainder = parts[1] if len(parts) > 1 else ""
        path = remainder.split(" ", 1)[0]
        status = _translate_submodule_status(status_char)
        commit_remote = _submodule_remote_commit(repo_path, branch, path, timeout)
        if status == "ok" and commit_remote and commit_remote != commit_local:
            status = "modified"
        submodules.append(
            {
                "path": path,
                "status": status,
                "commit_local": commit_local,
                "commit_remote": commit_remote or "",
            }
        )
    return submodules


def _translate_submodule_status(prefix: str) -> str:
    mapping = {
        " ": "ok",
        "-": "uninitialized",
        "+": "modified",
        "U": "missing",
    }
    return mapping.get(prefix, "modified")


def _submodule_remote_commit(
    repo_path: Path,
    branch: str,
    submodule_path: str,
    timeout: int,
) -> str | None:
    try:
        completed = run_git(
            ["git", "ls-tree", f"origin/{branch}", submodule_path],
            repo_path,
            timeout,
        )
    except GitCommandError:
        return None
    lines = completed.stdout.strip().splitlines()
    if not lines:
        return None
    meta, _, _ = lines[0].partition("\t")
    parts = meta.split()
    if len(parts) < 3:
        return None
    return parts[2]


def detect_lfs(repo_path: Path, timeout: int) -> dict[str, object]:
    """Detect git LFS usage and pointer mismatches."""
    gitattributes = repo_path / ".gitattributes"
    if not gitattributes.exists():
        return {"present": False, "pointer_mismatches": 0}

    try:
        contents = gitattributes.read_text(encoding="utf-8")
    except OSError:
        return {"present": False, "pointer_mismatches": 0}

    if "filter=lfs" not in contents:
        return {"present": False, "pointer_mismatches": 0}

    try:
        run_git(
            ["git", "lfs", "ls-files", "--all", "--error-exit"],
            repo_path,
            timeout,
        )
    except GitCommandError as exc:
        return {"present": True, "pointer_mismatches": max(1, abs(exc.returncode))}
    return {"present": True, "pointer_mismatches": 0}
