"""CLI entry point using Typer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

from .core import DEFAULT_REMOTE, SyncOptions, run


app = typer.Typer(
    pretty_exceptions_short=True,
    rich_markup_mode="rich",
)


@app.command()
def verify(
    path: Path = typer.Option(Path.cwd(), "--path", help="مسیر مخزن محلی."),
    remote: str = typer.Option(
        DEFAULT_REMOTE,
        "--remote",
        help="آدرس مخزن دور مورد انتظار.",
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        help="شاخهٔ مورد بررسی؛ در صورت عدم تعیین از origin/HEAD استفاده می‌شود.",
    ),
    timeout: int = typer.Option(
        30,
        "--timeout",
        min=1,
        help="مهلت اجرای دستورات شبکه‌ای (ثانیه).",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="مسیر تولید گزارش‌ها؛ پیش‌فرض ریشهٔ مخزن است.",
    ),
    machine: bool = typer.Option(
        False,
        "--machine",
        help="فقط خروجی JSON روی stdout برای پردازش خودکار.",
    ),
    fix_remote: bool = typer.Option(
        False,
        "--fix-remote",
        help="در صورت ناهماهنگی، آدرس origin را با مقدار استاندارد تنظیم می‌کند.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="تأیید اجرای عملیات‌های اصلاحی (بدون پرسش).",
    ),
    fix_submodules: bool = typer.Option(
        False,
        "--fix-submodules",
        help="در صورت فعال بودن، git submodule update --init --recursive اجرا می‌شود.",
    ),
    open_md: bool = typer.Option(
        False,
        "--open-md",
        help="پس از تولید گزارش، فایل sync_report.md را باز می‌کند.",
    ),
) -> None:
    """Entry point for git sync verification."""
    options = SyncOptions(
        path=path,
        remote=remote,
        branch=branch,
        timeout=timeout,
        out_dir=out,
        machine=machine,
        fix_remote=fix_remote,
        confirm_fix=yes,
        fix_submodules=fix_submodules,
    )
    outcome = run(options)
    if machine:
        print(json.dumps(outcome.report, ensure_ascii=False))
    else:
        print(outcome.message)
    if open_md:
        _open_markdown(outcome, options)
    raise typer.Exit(outcome.exit_code)


def main() -> None:
    """CLI wrapper for console_scripts compatibility."""
    app()


if __name__ == "__main__":
    main()


def _open_markdown(outcome, options: SyncOptions) -> None:
    md_path = (options.out_dir or Path(outcome.report["repo_root"])) / "sync_report.md"
    if not md_path.exists():
        return
    code_cmd = shutil.which("code")
    try:
        if code_cmd:
            subprocess.Popen([code_cmd, "-g", str(md_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if sys.platform.startswith("darwin"):
            subprocess.Popen(["open", str(md_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if os.name == "nt":
            os.startfile(str(md_path))  # type: ignore[arg-type]
            return
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(md_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Silent failure; task still succeeds.
        pass
