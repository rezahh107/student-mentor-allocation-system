"""CLI entrypoint for running the audit monthly archiver."""
from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy import create_engine
from zoneinfo import ZoneInfo

from src.audit import AuditArchiveConfig, AuditArchiver, ReleaseManifest
from src.audit.service import build_metrics
from src.reliability.clock import Clock
from src.reliability.logging_utils import JSONLogger, configure_logging


app = typer.Typer(help="Audit monthly archiver")


@app.command()
def run(
    month: str = typer.Argument(..., help="Month key in YYYY_MM format."),
    db_url: str = typer.Option(..., "--db-url", envvar="DATABASE_URL", help="Database connection string"),
    archive_root: Path = typer.Option(Path("archives"), help="Root directory for archives"),
    release_manifest_path: Path = typer.Option(Path("release.json"), help="Release manifest path"),
    dry_run: bool = typer.Option(False, help="Plan run without emitting artifacts"),
) -> None:
    configure_logging()
    logger = JSONLogger("audit.archiver")
    logger.info("audit.archiver.start", month=month, dry_run=dry_run)
    engine = create_engine(db_url)
    metrics = build_metrics()
    clock = Clock(ZoneInfo("Asia/Tehran"))
    release_manifest = ReleaseManifest(release_manifest_path)
    config = AuditArchiveConfig(archive_root=archive_root)
    archiver = AuditArchiver(
        engine=engine,
        metrics=metrics,
        clock=clock,
        release_manifest=release_manifest,
        config=config,
    )
    archiver.archive_month(month, dry_run=dry_run)
    logger.info("audit.archiver.complete", month=month, dry_run=dry_run)


if __name__ == "__main__":  # pragma: no cover
    app()
