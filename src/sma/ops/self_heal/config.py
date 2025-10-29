"""Configuration models for the Windows self-healing launcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SelfHealConfig:
    """Configuration required to orchestrate the self-healing workflow."""

    repo_root: Path
    runbook_path: Path
    reports_dir: Path
    metrics_token_env: str = "IMPORT_TO_SABT_AUTH__METRICS_TOKEN"
    port: int = 8000
    fallback_port: int = 8800
    max_health_attempts: int = 8
    health_interval_seconds: float = 1.0
    tz_name: str = "Asia/Tehran"

    def ensure_directories(self) -> None:
        """Create folders required for reporting."""

        self.reports_dir.mkdir(parents=True, exist_ok=True)


__all__ = ["SelfHealConfig"]
