"""CLI entrypoints for deployment and operational workflows."""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

import typer

from .backup import BackupManager
from .deploy import ReadinessGate, ZeroDowntimeHandoff
from .atomic import atomic_write

app = typer.Typer(help="ImportToSabt operational utilities")


@app.command("deploy")
def deploy_command(
    bundle: Path = typer.Argument(..., help="Path to staged bundle to deploy"),
    build_id: str = typer.Option(..., "--build-id", help="Build identifier"),
    releases_dir: Path = typer.Option(Path("releases"), "--releases-dir", help="Releases root"),
    lock_file: Path | None = typer.Option(None, "--lock-file", help="Override lock file"),
) -> None:
    releases_dir = Path(releases_dir)
    stage_dir = releases_dir / build_id
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    shutil.copytree(bundle, stage_dir)
    _switch_release(build_id=build_id, releases_dir=releases_dir, source=stage_dir, lock_file=lock_file)


@app.command("switch")
def switch_command(
    build_id: str = typer.Option(..., "--build-id"),
    source: Path = typer.Option(..., "--source"),
    releases_dir: Path = typer.Option(Path("releases"), "--releases-dir"),
    lock_file: Path | None = typer.Option(None, "--lock-file"),
) -> None:
    _switch_release(build_id=build_id, releases_dir=releases_dir, source=source, lock_file=lock_file)


def _switch_release(*, build_id: str, releases_dir: Path, source: Path, lock_file: Path | None) -> None:
    releases_dir = Path(releases_dir)
    source = Path(source)
    if not source.exists():
        raise typer.Exit(code=2)
    lock_path = lock_file or releases_dir / ".deploy.lock"
    handoff = ZeroDowntimeHandoff(
        releases_dir=releases_dir,
        lock_file=lock_path,
        clock=time.monotonic,
        sleep=time.sleep,
    )
    result = handoff.promote(build_id=build_id, source=source)
    typer.echo(
        json.dumps(
            {
                "build_id": result.build_id,
                "current": str(result.current_target),
                "previous": None if result.previous_target is None else str(result.previous_target),
            },
            ensure_ascii=False,
        )
    )


@app.command("rollback")
def rollback_command(
    releases_dir: Path = typer.Option(Path("releases"), "--releases-dir"),
    lock_file: Path | None = typer.Option(None, "--lock-file"),
) -> None:
    lock_path = lock_file or releases_dir / ".deploy.lock"
    handoff = ZeroDowntimeHandoff(
        releases_dir=releases_dir,
        lock_file=lock_path,
        clock=time.monotonic,
        sleep=time.sleep,
    )
    result = handoff.rollback()
    typer.echo(
        json.dumps(
            {
                "build_id": result.build_id,
                "current": str(result.current_target),
            },
            ensure_ascii=False,
        )
    )


@app.command("warmup")
def warmup_command(
    url: str = typer.Option(..., "--url", help="URL to probe"),
    readiness_timeout: float = typer.Option(30.0, "--timeout", help="Readiness timeout seconds"),
    gate_state: Path | None = typer.Option(None, "--gate-state", help="Optional state file"),
    attempts: int = typer.Option(5, "--attempts", help="Maximum probe attempts"),
) -> None:
    gate = ReadinessGate(clock=time.monotonic, readiness_timeout=readiness_timeout)
    start = time.monotonic()
    attempt = 0
    last_error = None
    while time.monotonic() - start < readiness_timeout and attempt < attempts:
        attempt += 1
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= response.status < 500:
                    gate.record_cache_warm()
                    gate.record_dependency(name="http", healthy=True)
                    break
        except Exception as exc:  # noqa: BLE001
            gate.record_dependency(name="http", healthy=False, error=str(exc))
            last_error = str(exc)
        time.sleep(min(0.5 * (2 ** attempt), 3.0))
    else:
        gate.record_dependency(name="timeout", healthy=False, error="probe timed out")

    if not gate.ready():
        message = {
            "ready": False,
            "error": last_error or "readiness gate not satisfied",
        }
        typer.echo(json.dumps(message, ensure_ascii=False))
        raise typer.Exit(code=1)

    if gate_state is not None:
        atomic_write(Path(gate_state), json.dumps({"ready": True}, ensure_ascii=False).encode("utf-8"))

    typer.echo(json.dumps({"ready": True}, ensure_ascii=False))


@app.command("backup")
def backup_command(
    destination: Path = typer.Option(..., "--destination"),
    sources: List[Path] = typer.Argument(..., help="Files to archive"),
) -> None:
    manager = BackupManager(clock=lambda: datetime.now(timezone.utc))
    bundle = manager.backup(sources=sources, destination=destination)
    typer.echo(
        json.dumps(
            {
                "directory": str(bundle.directory),
                "manifest": str(bundle.manifest),
                "entries": [entry.__dict__ for entry in bundle.entries],
            },
            ensure_ascii=False,
        )
    )


@app.command("restore")
def restore_command(
    manifest: Path = typer.Option(..., "--manifest"),
    destination: Path = typer.Option(..., "--destination"),
) -> None:
    manager = BackupManager(clock=lambda: datetime.now(timezone.utc))
    manager.restore(manifest=manifest, destination=destination)
    typer.echo(json.dumps({"restored": True}, ensure_ascii=False))


@app.command("retention")
def retention_command(
    root: Path = typer.Option(..., "--root"),
    max_age_days: int = typer.Option(..., "--max-age-days"),
    max_total_bytes: int = typer.Option(..., "--max-total-bytes"),
    enforce: bool = typer.Option(False, "--enforce/--dry-run"),
) -> None:
    manager = BackupManager(clock=lambda: datetime.now(timezone.utc))
    plan = manager.plan_retention(root=root, max_age_days=max_age_days, max_total_bytes=max_total_bytes)
    manager.apply_retention(plan=plan, enforce=enforce)
    typer.echo(
        json.dumps(
            {
                "decisions": [
                    {
                        "path": str(item.path),
                        "action": item.action,
                        "reason": item.reason,
                        "age_days": item.age_days,
                        "size": item.size,
                    }
                    for item in plan.decisions
                ],
                "freed_bytes": plan.freed_bytes,
                "kept_bytes": plan.kept_bytes,
                "enforce": enforce,
            },
            ensure_ascii=False,
        )
    )


def main(argv: Iterable[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    app(prog_name="phase7-release", args=args, standalone_mode=False)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
