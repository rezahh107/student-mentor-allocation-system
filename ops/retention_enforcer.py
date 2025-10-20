from __future__ import annotations

from pathlib import Path

import json
from pathlib import Path

import typer
from sqlalchemy import create_engine
from zoneinfo import ZoneInfo

from sma.audit import AuditArchiveConfig, AuditArchiver, AuditRetentionEnforcer, ReleaseManifest
from sma.audit.service import AuditMetrics, build_metrics as build_audit_metrics
from sma.reliability import ReliabilityMetrics, ReliabilitySettings, RetentionEnforcer
from sma.reliability.clock import Clock
from sma.reliability.logging_utils import JSONLogger, configure_logging

app = typer.Typer(help="Retention enforcer (dry-run then enforce).")


def _load_audit_config(config_path: Path) -> AuditArchiveConfig:
    payload = json.loads(config_path.read_text("utf-8"))
    archive_root = Path(payload["archive_root"])
    retention = payload.get("retention", {})
    return AuditArchiveConfig(
        archive_root=archive_root,
        csv_bom=bool(retention.get("csv_bom", True)),
        retention_age_days=retention.get("age_days"),
        retention_age_months=retention.get("age_months"),
        retention_size_bytes=retention.get("size_bytes"),
    )


def _build_archiver(
    db_url: str, config: AuditArchiveConfig, release_manifest: Path
) -> tuple[AuditArchiver, AuditMetrics]:
    engine = create_engine(db_url)
    metrics = build_audit_metrics()
    clock = Clock(ZoneInfo("Asia/Tehran"))
    manifest = ReleaseManifest(release_manifest)
    archiver = AuditArchiver(
        engine=engine,
        metrics=metrics,
        clock=clock,
        release_manifest=manifest,
        config=config,
    )
    return archiver, metrics


def _load_settings(config_path: Path) -> ReliabilitySettings:
    content = config_path.read_text(encoding="utf-8")
    return ReliabilitySettings.model_validate_json(content)


@app.command()
def run(
    config: Path = typer.Argument(..., help="Path to reliability settings JSON."),
    report_path: Path = typer.Option(Path("reports/retention/report.json"), help="Report destination."),
    csv_report_path: Path = typer.Option(
        Path("reports/retention/report.csv"), help="CSV evidence destination."
    ),
) -> None:
    settings = _load_settings(config)
    configure_logging()
    metrics = ReliabilityMetrics()
    logger = JSONLogger("reliability.retention")
    clock = settings.build_clock()
    enforcer = RetentionEnforcer(
        artifacts_root=settings.artifacts_root,
        backups_root=settings.backups_root,
        config=settings.retention,
        metrics=metrics,
        clock=clock,
        logger=logger,
        report_path=report_path,
        csv_report_path=csv_report_path,
        namespace=settings.redis.namespace,
    )
    enforcer.run(enforce=True)


@app.command()
def audit(
    month: str = typer.Argument(..., help="Month key to archive before enforcement"),
    db_url: str = typer.Option(..., "--db-url", envvar="DATABASE_URL"),
    archive_root: Path = typer.Option(Path("archives"), help="Root for audit archives"),
    release_manifest: Path = typer.Option(Path("release.json"), help="Release manifest"),
    retention_config: Path = typer.Option(Path("config/audit_retention.json"), help="Audit retention config"),
    dry_run: bool = typer.Option(False, help="Only plan retention"),
) -> None:
    configure_logging()
    logger = JSONLogger("audit.retention")
    logger.info("audit.retention.start", month=month, dry_run=dry_run)
    config = _load_audit_config(retention_config)
    config.archive_root = archive_root
    archiver, metrics = _build_archiver(db_url, config, release_manifest)
    archiver.archive_month(month, dry_run=False)
    enforcer = AuditRetentionEnforcer(
        engine=create_engine(db_url),
        archiver=archiver,
        metrics=metrics,
        config=config,
    )
    report = enforcer.enforce(dry_run=dry_run)
    logger.info("audit.retention.result", report=report)


if __name__ == "__main__":  # pragma: no cover
    app()
