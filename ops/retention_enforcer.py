from __future__ import annotations

from pathlib import Path

import typer

from src.reliability import ReliabilityMetrics, ReliabilitySettings, RetentionEnforcer
from src.reliability.logging_utils import JSONLogger, configure_logging

app = typer.Typer(help="Retention enforcer (dry-run then enforce).")


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


if __name__ == "__main__":  # pragma: no cover
    app()
