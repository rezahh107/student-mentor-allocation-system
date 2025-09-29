from __future__ import annotations

from pathlib import Path

import typer

from src.reliability import DisasterRecoveryDrill, ReliabilityMetrics, ReliabilitySettings
from src.reliability.logging_utils import JSONLogger, configure_logging

app = typer.Typer(help="Disaster recovery drill runner.")


def _load_settings(config_path: Path) -> ReliabilitySettings:
    content = config_path.read_text(encoding="utf-8")
    return ReliabilitySettings.model_validate_json(content)


@app.command()
def rehearsal(
    config: Path = typer.Argument(..., help="Path to reliability settings JSON."),
    source: Path = typer.Option(Path("artifacts"), help="Source directory for backup."),
    destination: Path = typer.Option(Path("tmp/restore"), help="Destination for restore."),
    correlation_id: str = typer.Option("dr-cli", help="Correlation identifier."),
    report_path: Path = typer.Option(Path("dr/rehearsal_report.json"), help="Report path."),
) -> None:
    settings = _load_settings(config)
    configure_logging()
    metrics = ReliabilityMetrics()
    logger = JSONLogger("reliability.dr")
    clock = settings.build_clock()
    drill = DisasterRecoveryDrill(
        backups_root=settings.backups_root,
        metrics=metrics,
        logger=logger,
        clock=clock,
        report_path=report_path,
    )
    drill.run(
        source,
        destination,
        correlation_id=correlation_id,
        namespace=settings.redis.namespace,
    )


if __name__ == "__main__":  # pragma: no cover
    app()
