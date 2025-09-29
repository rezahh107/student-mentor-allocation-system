from __future__ import annotations

from pathlib import Path

import typer

from src.reliability import CleanupDaemon, ReliabilityMetrics, ReliabilitySettings
from src.reliability.logging_utils import JSONLogger, configure_logging

app = typer.Typer(help="Cleanup daemon for .part files and expired links.")


def _load_settings(config_path: Path) -> ReliabilitySettings:
    content = config_path.read_text(encoding="utf-8")
    return ReliabilitySettings.model_validate_json(content)


@app.command()
def run(
    config: Path = typer.Argument(..., help="Path to reliability settings JSON."),
    registry_path: Path = typer.Option(Path("artifacts/signed_urls.json"), help="Signed URL registry path."),
    report_path: Path = typer.Option(
        Path("reports/cleanup/report.json"), help="Cleanup report destination."
    ),
) -> None:
    settings = _load_settings(config)
    configure_logging()
    metrics = ReliabilityMetrics()
    logger = JSONLogger("reliability.cleanup")
    clock = settings.build_clock()
    daemon = CleanupDaemon(
        artifacts_root=settings.artifacts_root,
        backups_root=settings.backups_root,
        config=settings.cleanup,
        metrics=metrics,
        clock=clock,
        logger=logger,
        registry_path=registry_path,
        namespace=settings.redis.namespace,
        report_path=report_path,
    )
    daemon.run()


if __name__ == "__main__":  # pragma: no cover
    app()
