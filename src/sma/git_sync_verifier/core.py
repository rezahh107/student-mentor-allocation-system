"""Core orchestration for git sync verification."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_csv, write_json, write_markdown
from .clock import Clock, default_clock
from .constants import BRANCH_REGEX, REMOTE_REGEX
from .exceptions import GitCommandError, SyncProcessError
from .git_ops import (
    count_untracked,
    detect_lfs,
    fetch_with_retry,
    get_ahead_behind,
    get_default_branch,
    get_head_commit,
    get_ref_commit,
    get_remote_url,
    get_repo_root,
    get_status_porcelain,
    has_dirty_changes,
    is_detached,
    is_shallow,
    list_submodules,
    run_git,
    tags_aligned,
)
from .lock import repo_lock
from .logging_utils import mask_path, setup_logging
from .metrics import SyncMetrics


DEFAULT_REMOTE = "https://github.com/rezahh107/student-mentor-allocation-system.git"


@dataclass(frozen=True)
class SyncOptions:
    """User-facing options."""

    path: Path
    remote: str
    branch: str | None
    timeout: int
    out_dir: Path | None
    machine: bool
    fix_remote: bool
    confirm_fix: bool
    fix_submodules: bool


@dataclass
class SyncOutcome:
    """Result of sync run."""

    exit_code: int
    status: str
    message: str
    report: dict[str, Any]


def run(options: SyncOptions, *, clock: Clock | None = None, metrics: SyncMetrics | None = None) -> SyncOutcome:
    """Execute sync verification."""
    clock = clock or default_clock()
    metrics = metrics or SyncMetrics()
    correlation_id = os.environ.get("CORRELATION_ID", str(uuid.uuid4()))
    logger = setup_logging(correlation_id)
    metrics.record_attempt()
    start_ms = clock.monotonic_ms()

    try:
        outcome = _execute(
            options=options,
            clock=clock,
            metrics=metrics,
            correlation_id=correlation_id,
            logger=logger,
            start_ms=start_ms,
        )
        return outcome
    except SyncProcessError as err:
        timing_ms = max(0, clock.monotonic_ms() - start_ms)
        metrics.record_exit_code(err.exit_code)
        report = _error_report(
            err=err,
            options=options,
            correlation_id=correlation_id,
            timing_ms=timing_ms,
        )
        out_dir = options.out_dir or options.path.resolve()
        write_json(report, out_dir / "sync_report.json")
        write_csv(report, out_dir / "sync_report.csv")
        write_markdown(report, out_dir / "sync_report.md")
        message = err.args[0]
        return SyncOutcome(exit_code=err.exit_code, status=err.status, message=message, report=report)


def _execute(
    *,
    options: SyncOptions,
    clock: Clock,
    metrics: SyncMetrics,
    correlation_id: str,
    logger,
    start_ms: int,
) -> SyncOutcome:
    path = options.path.expanduser().resolve()
    _ensure_git_directory(path)

    try:
        repo_root = get_repo_root(path, options.timeout)
    except GitCommandError as exc:
        raise SyncProcessError(
            "«مسیر انتخاب‌شده مخزن Git معتبر نیست؛ اجرای git rev-parse ناموفق بود.»",
            exit_code=9,
            status="error",
        ) from exc

    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        raise SyncProcessError(
            "«پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید.»",
            exit_code=10,
            status="error",
        )

    remote_expected = options.remote or DEFAULT_REMOTE
    if not REMOTE_REGEX.fullmatch(remote_expected):
        raise SyncProcessError(
            "«آدرس مخزن دور نامعتبر است؛ فقط آدرس تعیین‌شده برای پروژه مجاز است.»",
            exit_code=10,
            status="error",
        )

    try:
        remote_actual = get_remote_url(repo_root, options.timeout)
    except GitCommandError as exc:
        raise SyncProcessError(
            "«دریافت آدرس origin ناموفق بود؛ لطفاً تنظیمات Git را بررسی کنید.»",
            exit_code=9,
            status="error",
        ) from exc

    normalized_expected = _normalize_remote(remote_expected)
    normalized_actual = _normalize_remote(remote_actual)

    if not _remotes_equivalent(
        actual=normalized_actual,
        expected=normalized_expected,
        repo_root=repo_root,
        timeout=options.timeout,
    ):
        if options.fix_remote and options.confirm_fix:
            run_git(["git", "remote", "set-url", "origin", remote_expected], repo_root, options.timeout)
            remote_actual = get_remote_url(repo_root, options.timeout)
            normalized_actual = _normalize_remote(remote_actual)
        elif not _remotes_equivalent(
            actual=_normalize_remote(remote_actual),
            expected=normalized_expected,
            repo_root=repo_root,
            timeout=options.timeout,
        ):
            raise SyncProcessError(
                "«آدرس origin با مقدار مورد انتظار یکسان نیست؛ لطفاً اصلاح کنید.»",
                exit_code=6,
                status="remote_mismatch",
                context={"remote_actual": remote_actual},
            )

    branch = options.branch
    if branch:
        if not BRANCH_REGEX.fullmatch(branch):
            raise SyncProcessError(
                "«نام شاخه نامعتبر است؛ فقط حروف، اعداد و ./_- مجاز هستند.»",
                exit_code=10,
                status="error",
            )
    else:
        try:
            branch = get_default_branch(repo_root, options.timeout)
        except GitCommandError as exc:
            raise SyncProcessError(
                "«تشخیص شاخهٔ پیش‌فرض origin ناموفق بود.»",
                exit_code=9,
                status="error",
            ) from exc

    try:
        default_branch = get_default_branch(repo_root, options.timeout)
    except GitCommandError as exc:
        raise SyncProcessError(
            "«تشخیص شاخهٔ پیش‌فرض origin ناموفق بود.»",
            exit_code=9,
            status="error",
        ) from exc

    if options.fix_submodules:
        try:
            run_git(["git", "submodule", "update", "--init", "--recursive"], repo_root, options.timeout)
        except GitCommandError:
            # Non-fatal; drift will be reported later.
            pass

    with repo_lock(repo_root):
        fetch_result, fetch_attempts, fetch_retries, middleware_trace = fetch_with_retry(
            repo_root,
            "origin",
            remote_expected,
            options.timeout,
            max_attempts=4,
            base_delay_ms=150,
            clock=clock,
            logger=logger,
            metrics=metrics,
            correlation_id=correlation_id,
        )

    metrics.record_retries(fetch_retries)

    if not fetch_result.success:
        raise SyncProcessError(
            "«اجرای git fetch ناموفق بود؛ بررسی شبکه یا دسترسی لازم است.»",
            exit_code=9,
            status="error",
        )

    head_local = get_head_commit(repo_root, options.timeout)
    try:
        head_remote = get_ref_commit(repo_root, f"origin/{branch}", options.timeout)
    except GitCommandError as exc:
        raise SyncProcessError(
            "«شاخهٔ مورد نظر در origin یافت نشد؛ لطفاً آن را بررسی کنید.»",
            exit_code=9,
            status="error",
        ) from exc
    ahead, behind = get_ahead_behind(repo_root, branch, options.timeout)
    submodules = list_submodules(repo_root, branch, options.timeout)
    porcelain = get_status_porcelain(repo_root, options.timeout)
    submodule_paths = {entry["path"] for entry in submodules}
    dirty = has_dirty_changes(porcelain, submodule_paths=submodule_paths)
    untracked = count_untracked(porcelain)
    tags_ok = tags_aligned(repo_root, options.timeout)
    lfs_info = detect_lfs(repo_root, options.timeout)
    shallow = is_shallow(repo_root, options.timeout)
    detached = is_detached(repo_root, options.timeout)

    status = _derive_status(
        dirty=dirty,
        submodules=submodules,
        lfs_info=lfs_info,
        shallow=shallow,
        detached=detached,
        ahead=ahead,
        behind=behind,
        tags_ok=tags_ok,
    )
    exit_code = _status_to_exit_code(status)
    metrics.record_exit_code(exit_code)

    timing_ms = max(0, clock.monotonic_ms() - start_ms)

    repo_report: dict[str, Any] = {
        "correlation_id": correlation_id,
        "path": str(repo_root),
        "remote_expected": remote_expected,
        "remote_actual": remote_actual,
        "default_branch": default_branch,
        "branch_checked": branch,
        "head_local": head_local,
        "head_remote": head_remote,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "untracked_count": untracked,
        "submodules": submodules,
        "lfs": lfs_info,
        "tags_aligned": tags_ok,
        "shallow": shallow,
        "detached": detached,
        "repo_root": str(repo_root),
        "timing_ms": timing_ms,
        "metrics": {
            "fetch_attempts": fetch_attempts,
            "retries": fetch_retries,
        },
        "status": status,
        "exit_code": exit_code,
        "evidence": [
            "git.remote.show:origin",
            "git.rev-parse:HEAD",
            "git.status:porcelain",
            "AGENTS.md::Project TL;DR",
        ],
        "middleware_trace": middleware_trace,
    }

    out_dir = options.out_dir or repo_root
    json_path = out_dir / "sync_report.json"
    csv_path = out_dir / "sync_report.csv"
    md_path = out_dir / "sync_report.md"
    write_json(repo_report, json_path)
    write_csv(repo_report, csv_path)
    write_markdown(repo_report, md_path)

    message = _status_message(status)
    return SyncOutcome(exit_code=exit_code, status=status, message=message, report=repo_report)


def _error_report(
    *,
    err: SyncProcessError,
    options: SyncOptions,
    correlation_id: str,
    timing_ms: int,
) -> dict[str, Any]:
    path = options.path.expanduser().resolve()
    report = {
        "correlation_id": correlation_id,
        "path": str(path),
        "remote_expected": options.remote,
        "remote_actual": str(err.context.get("remote_actual", "")),
        "default_branch": "",
        "branch_checked": options.branch or "",
        "head_local": "",
        "head_remote": "",
        "ahead": 0,
        "behind": 0,
        "dirty": False,
        "untracked_count": 0,
        "submodules": [],
        "lfs": {"present": False, "pointer_mismatches": 0},
        "tags_aligned": False,
        "shallow": False,
        "detached": False,
        "repo_root": str(path),
        "timing_ms": timing_ms,
        "metrics": {"fetch_attempts": 0, "retries": 0},
        "status": err.status,
        "exit_code": err.exit_code,
        "evidence": [
            "git.remote.show:origin",
            "AGENTS.md::Missing",
        ],
        "error": err.args[0],
    }
    return report


def _normalize_remote(remote: str) -> str:
    remote = remote.rstrip("/")
    while remote.endswith(".git"):
        remote = remote[:-4]
    return remote


def _remotes_equivalent(
    *,
    actual: str,
    expected: str,
    repo_root: Path,
    timeout: int,
) -> bool:
    if actual == expected:
        return True
    try:
        config_output = run_git(
            ["git", "config", "--get-regexp", r"^url\..*\.insteadOf$"],
            repo_root,
            timeout,
        ).stdout.splitlines()
    except GitCommandError:
        return False
    for line in config_output:
        if not line.strip():
            continue
        key, _, value = line.partition(" ")
        alias = key.removeprefix("url.")
        if alias.endswith(".insteadOf"):
            alias = alias[: -len(".insteadOf")]
        elif alias.endswith(".insteadof"):
            alias = alias[: -len(".insteadof")]
        if _normalize_remote(value.strip()) == expected and _normalize_remote(alias) == actual:
            return True
    return False


def _ensure_git_directory(path: Path) -> None:
    for candidate in [path] + list(path.parents):
        git_dir = candidate / ".git"
        if git_dir.exists():
            return
    raise SyncProcessError(
        "«مسیر انتخاب‌شده مخزن Git معتبر نیست؛ پوشهٔ .git یافت نشد.»",
        exit_code=9,
        status="error",
    )


def _derive_status(
    *,
    dirty: bool,
    submodules: list[dict[str, Any]],
    lfs_info: dict[str, Any],
    shallow: bool,
    detached: bool,
    ahead: int,
    behind: int,
    tags_ok: bool,
) -> str:
    if dirty:
        return "dirty"
    drift = any(entry["status"] != "ok" for entry in submodules)
    lfs_drift = bool(lfs_info.get("present") and lfs_info.get("pointer_mismatches", 0))
    if drift or lfs_drift:
        return "submodule_drift"
    if shallow or detached:
        return "shallow_or_detached"
    if not tags_ok:
        return "diverged"
    if ahead > 0 and behind > 0:
        return "diverged"
    if ahead > 0:
        return "ahead"
    if behind > 0:
        return "behind"
    return "in_sync"


def _status_to_exit_code(status: str) -> int:
    mapping = {
        "in_sync": 0,
        "behind": 2,
        "ahead": 3,
        "diverged": 4,
        "dirty": 5,
        "remote_mismatch": 6,
        "submodule_drift": 7,
        "shallow_or_detached": 8,
        "error": 9,
    }
    return mapping.get(status, 9)


def _status_message(status: str) -> str:
    messages = {
        "in_sync": "«مخزن کاملاً با مبدأ همگام است.»",
        "behind": "«مخزن محلی از مبدأ عقب است؛ دستور pull را اجرا کنید.»",
        "ahead": "«مخزن محلی جلوتر است؛ push لازم است.»",
        "diverged": "«شاخهٔ محلی و مبدأ واگرا شده‌اند؛ ابتدا وضعیت را بررسی کنید.»",
        "dirty": "«تغییرات ثبت‌نشده وجود دارد؛ ابتدا آن‌ها را مدیریت کنید.»",
        "remote_mismatch": "«آدرس origin با مقدار استاندارد مطابقت ندارد.»",
        "submodule_drift": "«زیرماژول یا فایل‌های LFS نیاز به به‌روزرسانی دارند.»",
        "shallow_or_detached": "«مخزن ناقص یا HEAD جدا شده است؛ ابتدا ترمیم کنید.»",
        "error": "«خطای غیرمنتظره رخ داد؛ جزییات را در گزارش ببینید.»",
    }
    return messages.get(status, "«خطای ناشناخته رخ داد.»")
