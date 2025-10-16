"""Readiness report assembly and artifact generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .checks import CheckResult, SharedState, format_csv_rows
from .config import CLIConfig
from .fs import atomic_write_bytes, atomic_write_text, ensure_crlf, normalize_text


@dataclass(slots=True)
class ReadinessReport:
    correlation_id: str
    repo_root: str
    remote_expected: str
    remote_actual: str
    python_required: str
    python_found: str
    venv_path: str
    env_file: str
    port: int
    git: Dict[str, Any]
    powershell: Dict[str, Any]
    dependencies_ok: bool
    smoke: Dict[str, Any]
    status: str
    score: int
    exit_code: int
    timing_ms: int
    metrics: Dict[str, Any]
    evidence: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def build_report(
    *,
    config: CLIConfig,
    state: SharedState,
    correlation_id: str,
    score: int,
    exit_code: int,
    git_data: Dict[str, Any],
    results: Sequence[CheckResult],
    metrics: Dict[str, Any],
) -> ReadinessReport:
    evidence = list(dict.fromkeys(state.evidence))
    status = "ready" if score == 100 and exit_code == 0 else "blocked"
    smoke_dict = {
        "readyz": state.smoke.readyz,
        "metrics": state.smoke.metrics,
        "ui_head": state.smoke.ui_head,
    }
    git_section = {
        "present": git_data.get("present", False),
        "ahead": git_data.get("ahead", 0),
        "behind": git_data.get("behind", 0),
        "dirty": git_data.get("dirty", False),
    }
    powershell_section = {
        "version": state.powershell.version,
        "execution_policy": state.powershell.execution_policy or "Unknown",
    }
    if state.powershell.path:
        powershell_section["path"] = state.powershell.path

    if "AGENTS.md::Project TL;DR" not in evidence:
        evidence.append("AGENTS.md::Project TL;DR")

    return ReadinessReport(
        correlation_id=correlation_id,
        repo_root=str(config.repo_root),
        remote_expected=config.remote_expected,
        remote_actual=state.remote_actual,
        python_required=config.python_required,
        python_found=state.python_found,
        venv_path=str(config.venv_path),
        env_file=str(config.env_file),
        port=config.port,
        git=git_section,
        powershell=powershell_section,
        dependencies_ok=state.dependencies_ok,
        smoke=smoke_dict,
        status=status,
        score=score,
        exit_code=exit_code,
        timing_ms=state.timing_ms,
        metrics=metrics,
        evidence=evidence,
    )


class ArtifactWriter:
    """Writes readiness artifacts atomically."""

    def __init__(self, directory: Path, *, jitter) -> None:
        self._directory = directory
        self._jitter = jitter

    def write_json(self, report: ReadinessReport) -> Path:
        path = self._directory / "readiness_report.json"
        atomic_write_text(path, report.to_json(), jitter=self._jitter)
        return path

    def write_csv(self, results: Sequence[CheckResult]) -> Path:
        path = self._directory / "readiness_report.csv"
        payload = format_csv_rows(results)
        atomic_write_bytes(path, payload, jitter=self._jitter)
        return path

    def write_markdown(self, report: ReadinessReport, results: Sequence[CheckResult]) -> Path:
        path = self._directory / "readiness_report.md"
        lines = ["# گزارش آمادگی", "", f"- وضعیت کلی: **{report.status}** ({report.score}/100)", ""]
        for result in results:
            lines.append(f"- {result.name}: {result.status.name} – {normalize_text(result.detail)}")
        content = ensure_crlf("\n".join(lines) + "\n")
        atomic_write_text(path, content, jitter=self._jitter)
        return path

    def write_all(self, report: ReadinessReport, results: Sequence[CheckResult]) -> List[Path]:
        self._directory.mkdir(parents=True, exist_ok=True)
        written = [
            self.write_json(report),
            self.write_csv(results),
            self.write_markdown(report, results),
        ]
        return written


__all__ = [
    "ArtifactWriter",
    "ReadinessReport",
    "build_report",
]

