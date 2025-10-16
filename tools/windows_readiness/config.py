"""Configuration models for the readiness CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CLIConfig:
    repo_root: Path
    remote_expected: str
    python_required: str
    venv_path: Path
    env_file: Path
    port: int
    timeout: int
    fix: bool
    out_dir: Path
    machine_output: bool
    assume_yes: bool


__all__ = ["CLIConfig"]

