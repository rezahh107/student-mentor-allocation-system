from __future__ import annotations

from pathlib import Path
from typing import List

import typer

from src.reliability import Clock, RedisFlapInjector, ReliabilityMetrics, ReliabilitySettings
from src.reliability.logging_utils import JSONLogger, configure_logging

app = typer.Typer(help="Redis chaos-lite fault injector.")


def _load_settings(config_path: Path) -> ReliabilitySettings:
    content = config_path.read_text(encoding="utf-8")
    return ReliabilitySettings.model_validate_json(content)


@app.command()
def flap(
    config: Path = typer.Argument(..., help="Path to reliability settings JSON."),
    plan: str = typer.Option("1,0", help="Comma separated fault plan (1=inject,0=success)."),
    report_dir: Path = typer.Option(Path("reports/chaos"), help="Directory for chaos reports."),
    correlation_id: str | None = typer.Option(None, help="Correlation identifier."),
) -> None:
    settings = _load_settings(config)
    configure_logging()
    metrics = ReliabilityMetrics()
    logger = JSONLogger("reliability.chaos")
    clock = Clock(settings.clock())
    scenario = RedisFlapInjector(
        name="redis_flap",
        metrics=metrics,
        logger=logger,
        clock=clock,
        reports_root=report_dir,
    )
    plan_values: List[int] = [int(value.strip() or "0") for value in plan.split(",") if value.strip() or value == "0"]
    scenario.run(lambda: True, fault_plan=plan_values, correlation_id=correlation_id, namespace=settings.redis.namespace)


if __name__ == "__main__":  # pragma: no cover
    app()
