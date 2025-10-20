#!/usr/bin/env python3
"""Bootstrap helper for CI workflow patching and optional reruns."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from tools import gha_rerun
from tools import gha_workflow_patcher
from sma.core.clock import Clock


class BootstrapError(RuntimeError):
    """Domain-specific error for bootstrap flow."""


def _perr(code: str, message: str) -> BootstrapError:
    return BootstrapError(f"{code}: {message}")


def _run_patcher(root: Path, workflow: str, dry_run: bool, force_text: bool) -> int:
    argv: List[str] = [str(root)]
    if workflow:
        argv.extend(["--workflow", workflow])
    if dry_run:
        argv.append("--dry-run")
    if force_text:
        argv.append("--force-text")
    return gha_workflow_patcher.run(argv)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - system configuration
        raise _perr(
            "GIT_NOT_FOUND",
            "دستور git در سیستم یافت نشد؛ لطفاً نصب و PATH را بررسی کنید",
        ) from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "خطای نامشخص"
        raise _perr(
            "GIT_COMMAND_FAILED",
            f"اجرای git {' '.join(args)} با خطا متوقف شد: {message}",
        )
    return result


def _has_changes(root: Path) -> bool:
    result = _git(["status", "--porcelain"], root)
    return bool(result.stdout.strip())


def _ensure_git_available() -> None:
    if shutil.which("git") is None:
        raise _perr(
            "GIT_NOT_FOUND",
            "دستور git در محیط فعلی یافت نشد؛ git را نصب یا PATH را اصلاح کنید",
        )


def _print_guidance(branch_name: str) -> None:
    print(
        "\n".join(
            [
                "لطفاً مراحل زیر را برای نهایی‌سازی تغییرات انجام دهید:",
                f"  git checkout -b {branch_name}",
                "  git add .github/workflows tools/ci_bootstrap.py tools/gha_workflow_patcher.py tools/gha_rerun.py ci/snippets",
                "  git commit -m 'پیکربندی اجرای pytest در CI'",
                "  git push --set-upstream origin " + branch_name,
            ]
        )
    )


def _ensure_clean_worktree(root: Path) -> None:
    status = _git(["status", "--porcelain"], root)
    if status.stdout.strip():
        raise _perr(
            "GIT_DIRTY",
            "شاخه دارای تغییر ذخیره‌نشده است؛ ابتدا تغییرات را commit یا stash کنید",
        )


def _validate_remote(root: Path, remote: str, branch: str) -> None:
    try:
        _git(["remote", "get-url", remote], root)
    except BootstrapError as exc:
        raise _perr(
            "GIT_REMOTE_INVALID",
            f"دسترسی push به ریموت {remote} تأیید نشد؛ جزئیات: {exc}",
        )
    try:
        _git([
            "push",
            "--dry-run",
            remote,
            f"HEAD:{branch}",
        ], root)
    except BootstrapError as exc:
        raise _perr(
            "GIT_REMOTE_INVALID",
            f"دسترسی push به ریموت {remote} تأیید نشد؛ شاخه {branch} قابل دسترس نیست ({exc})",
        )


def _auto_flow(root: Path, branch_name: str, workflow: str, remote: str) -> None:
    original_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip()
    _validate_remote(root, remote, branch_name)
    _git(["checkout", "-b", branch_name], root)
    try:
        _git(["add", "-A"], root)
        _git(["commit", "-m", "Apply CI pytest runner automation patch"], root)
        _git(["push", "--set-upstream", remote, branch_name], root)
        rerun_rc = gha_rerun.run(["--workflow", workflow])
        if rerun_rc != 0:
            raise _perr(
                "RERUN_FAILED",
                "اجرای gha_rerun با خطای غیر صفر پایان یافت؛ لطفاً خروجی را بررسی کنید",
            )
    finally:
        try:
            _git(["checkout", original_branch], root)
        except BootstrapError:
            pass


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap CI configuration updates")
    parser.add_argument("root", nargs="?", default=".", help="ریشه مخزن")
    parser.add_argument("--workflow", default="ci.yml", help="نام فایل گردش‌کار")
    parser.add_argument("--dry-run", action="store_true", help="فقط پیش‌نمایش")
    parser.add_argument("--force-text", action="store_true", help="اجبار به ویرایش متنی")
    parser.add_argument("--auto", action="store_true", help="commit/push خودکار در صورت نیاز")
    parser.add_argument(
        "--branch-prefix",
        default="ci/runner-matrix",
        help="پیشوند شاخه موقت",
    )
    parser.add_argument("--branch", help="نام شاخهٔ دلخواه برای commit خودکار")
    parser.add_argument("--remote", default="origin", help="ریموت هدف برای push")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        _ensure_git_available()
        _ensure_clean_worktree(root)
        rc = _run_patcher(root, args.workflow, args.dry_run, args.force_text)
        if rc != 0 or args.dry_run:
            return rc

        if not _has_changes(root):
            print("تغییری برای commit وجود ندارد؛ CI در وضعیت جدید است")
            return 0

        branch_suffix = int(Clock.for_tehran().now().timestamp())
        branch_name = args.branch or f"{args.branch_prefix}-{branch_suffix}"
        token_present = bool(os.environ.get("GITHUB_TOKEN"))
        if args.auto and token_present:
            _auto_flow(root, branch_name, args.workflow, args.remote)
        else:
            _print_guidance(branch_name)
            if not token_present and args.auto:
                print("AUTO_SKIP: متغیر GITHUB_TOKEN تنظیم نشده بود؛ راهنمای دستی نمایش داده شد")
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def main() -> int:  # pragma: no cover
    try:
        return run()
    except Exception as exc:  # pragma: no cover - bootstrap level error
        print(f"BOOTSTRAP_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
