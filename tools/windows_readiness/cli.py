"""Typer CLI entrypoint for Windows readiness verification."""

from __future__ import annotations

import json
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Optional

import typer

from .checks import CheckContext, CheckResult, SharedState, run_checks
from .clock import DeterministicClock
from .config import CLIConfig
from .logging import JsonLogger
from .lock import ReadinessLock
from .metrics import ReadinessMetrics
from .report import ArtifactWriter, build_report
from .fs import atomic_write_text

app = typer.Typer(add_completion=False, help="Student Mentor Allocation System readiness verifier.")


def _derive_correlation_id(repo_root: Path) -> str:
    env_value = os.environ.get("CORRELATION_ID")
    if env_value:
        return env_value
    return str(uuid.uuid5(uuid.NAMESPACE_URL, repo_root.as_uri()))


def _resolve_path(base: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    return candidate


def _update_vscode_tasks(repo_root: Path, logger: JsonLogger) -> None:
    vscode_dir = repo_root / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = vscode_dir / "tasks.json"
    tasks_data = {"version": "2.0.0", "tasks": []}
    if tasks_path.exists():
        try:
            tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("invalid_tasks_json", path=str(tasks_path))

    tasks = list(tasks_data.get("tasks", []))

    cli_task = {
        "label": "Windows: Verify & Run",
        "type": "shell",
        "command": "pwsh",
        "args": [
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "${workspaceFolder}/windows_shared/Invoke-WindowsReadiness.ps1",
        ],
        "presentation": {"reveal": "always", "panel": "shared", "clear": True},
        "problemMatcher": [],
    }

    existing_labels = {task.get("label") for task in tasks}
    if cli_task["label"] not in existing_labels:
        tasks.append(cli_task)
        tasks_data["tasks"] = tasks
        atomic_write_text(tasks_path, json.dumps(tasks_data, ensure_ascii=False, indent=2) + "\n")
        logger.info("updated_vscode_tasks", path=str(tasks_path))


def _select_exit_code(results: list[CheckResult], score: int) -> int:
    for result in results:
        if result.exit_code is not None:
            return result.exit_code
    return 0 if score == 100 else 3


def _print_persian_instructions(report_path: Path) -> None:
    instructions = textwrap.dedent(
        f"""
        چگونه اجرا کنم:
        1) در PowerShell دستور زیر را اجرا کنید:
           pwsh -NoProfile -File windows_shared/Invoke-WindowsReadiness.ps1 --path .
        2) در VS Code، تسک «Windows: Verify & Run» را اجرا کنید.
        3) گزارش آماده‌سازی در فایل {report_path.as_posix()} قرار دارد.
        """
    ).strip()
    print(instructions)


@app.command()
def run(
    path: str = typer.Option(".", "--path", help="مسیر ریشهٔ مخزن."),
    remote: str = typer.Option(
        "https://github.com/rezahh107/student-mentor-allocation-system.git",
        "--remote",
        help="آدرس remote مورد انتظار.",
    ),
    python: str = typer.Option("3.11", "--python", help="نسخهٔ موردنیاز پایتون (major.minor)."),
    venv: str = typer.Option(".venv", "--venv", help="مسیر محیط مجازی."),
    env_file: str = typer.Option(".env.dev", "--env-file", help="پروندهٔ env برای اپلیکیشن."),
    port: int = typer.Option(25119, "--port", help="پورت مورد انتظار اپلیکیشن."),
    timeout: int = typer.Option(30, "--timeout", help="زمان‌سنج ثانیه‌ای برای عملیات شبکه/فرآیند."),
    fix: bool = typer.Option(False, "--fix", help="تلاش برای رفع خودکار مشکلات."),
    out: Optional[str] = typer.Option(None, "--out", help="مسیر خروجی برای گزارش‌ها."),
    machine: bool = typer.Option(False, "--machine", help="چاپ خروجی JSON-only برای CI."),
    yes: bool = typer.Option(False, "--yes", help="تأیید خودکار عملیات اصلاحی."),
) -> None:
    repo_root = Path(path).resolve()
    out_dir = Path(out).resolve() if out else (repo_root / "artifacts")
    config = CLIConfig(
        repo_root=repo_root,
        remote_expected=remote,
        python_required=python,
        venv_path=_resolve_path(repo_root, venv),
        env_file=_resolve_path(repo_root, env_file),
        port=port,
        timeout=timeout,
        fix=fix,
        out_dir=out_dir,
        machine_output=machine,
        assume_yes=yes,
    )

    correlation_id = _derive_correlation_id(repo_root)
    clock = DeterministicClock(correlation_id)
    logger = JsonLogger(stream=sys.stderr, clock=clock, correlation_id=correlation_id)
    metrics = ReadinessMetrics()
    metrics.record_attempt()

    lock_path = repo_root / ".readiness.lock"
    state = SharedState()
    results: list[CheckResult] = []
    exit_code = 0

    try:
        with ReadinessLock(lock_path):
            ctx = CheckContext(config, state, logger, clock, metrics)
            results, score = run_checks(ctx)
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.error("unexpected_failure", error=str(exc.__class__.__name__), message=str(exc))
        exit_code = 9
        report = build_report(
            config=config,
            state=state,
            correlation_id=correlation_id,
            score=0,
            exit_code=exit_code,
            git_data={"present": False, "ahead": 0, "behind": 0, "dirty": False},
            results=results,
            metrics={"attempts": 1, "retries": state.retries},
        )
        writer = ArtifactWriter(config.out_dir, jitter=clock.jitter_seconds)
        writer.write_all(report, results)
        metrics.record_exit_code(exit_code)
        raise typer.Exit(code=exit_code)

    git_data = {
        "present": state.git.present,
        "ahead": state.git.ahead,
        "behind": state.git.behind,
        "dirty": state.git.dirty,
    }
    score = min(score, 100)
    exit_code = _select_exit_code(results, score)
    metrics.record_exit_code(exit_code)
    metrics.record_duration(state.timing_ms / 1000.0 if state.timing_ms else 0.0)

    report = build_report(
        config=config,
        state=state,
        correlation_id=correlation_id,
        score=score,
        exit_code=exit_code,
        git_data=git_data,
        results=results,
        metrics={"attempts": 1, "retries": state.retries},
    )

    writer = ArtifactWriter(config.out_dir, jitter=clock.jitter_seconds)
    paths = writer.write_all(report, results)

    _update_vscode_tasks(repo_root, logger)

    if config.machine_output:
        print(report.to_json().strip())
    else:
        summary = f"وضعیت: {report.status} (امتیاز {report.score}/100، کد خروج {exit_code})"
        print(summary)
        if exit_code == 0:
            _print_persian_instructions(paths[-1])

    raise typer.Exit(code=exit_code)


def main() -> None:
    """Entrypoint when executed as a module."""

    app()


if __name__ == "__main__":  # pragma: no cover
    main()
