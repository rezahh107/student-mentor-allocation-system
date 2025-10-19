from __future__ import annotations

import pathlib
import sys
from typing import Optional

import typer

from src.repo_doctor import RepoDoctor
from src.repo_doctor.core import DoctorConfig
from src.repo_doctor.clock import tehran_clock

app = typer.Typer(add_completion=False, help="Repo Doctor CLI")


def _build_doctor(apply: bool) -> RepoDoctor:
    root = pathlib.Path(__file__).resolve().parents[1]
    config = DoctorConfig(root=root, apply=apply, clock=tehran_clock())
    return RepoDoctor(config)


@app.command()
def scan(apply: bool = typer.Option(False, "--apply", help="Apply fixes")) -> None:
    """Scan the repository for import inconsistencies."""

    doctor = _build_doctor(apply)
    report = doctor.scan()
    typer.echo(report.as_dict())


@app.command()
def fix(apply: bool = typer.Option(False, "--apply", help="Apply fixes")) -> None:
    """Apply import fixes and environment hygiene."""

    doctor = _build_doctor(apply)
    report = doctor.fix()
    typer.echo(report.as_dict())


@app.command()
def deps(apply: bool = typer.Option(False, "--apply", help="Write runtime requirements")) -> None:
    """Generate runtime requirements and probe dependencies."""

    doctor = _build_doctor(apply)
    report = doctor.deps()
    typer.echo(report.as_dict())


@app.command()
def health(apply: bool = typer.Option(False, "--apply", help="Allow shim creation")) -> None:
    """Run deterministic FastAPI health-check."""

    doctor = _build_doctor(apply)
    report = doctor.health()
    typer.echo(report.as_dict())


@app.command()
def all(apply: bool = typer.Option(False, "--apply", help="Apply fixes")) -> None:
    """Run the full remediation suite."""

    doctor = _build_doctor(apply)
    reports = doctor.run_all()
    typer.echo([report.as_dict() for report in reports])


if __name__ == "__main__":
    app()
