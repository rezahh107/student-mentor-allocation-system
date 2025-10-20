from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .atomic import atomic_write_json
from .clock import Clock
from .config import RetentionConfig
from .logging_utils import JSONLogger, persian_error
from .metrics import ReliabilityMetrics


@dataclass(slots=True)
class RetentionFinding:
    path: Path
    reason: str
    age_days: int
    size_bytes: int


class RetentionEnforcer:
    def __init__(
        self,
        *,
        artifacts_root: Path,
        backups_root: Path,
        config: RetentionConfig,
        metrics: ReliabilityMetrics,
        clock: Clock,
        logger: JSONLogger,
        report_path: Path,
        csv_report_path: Path | None = None,
        namespace: str = "default",
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.backups_root = Path(backups_root)
        self.config = config
        self.metrics = metrics
        self.clock = clock
        self.logger = logger
        self.report_path = Path(report_path)
        self.csv_report_path = (
            Path(csv_report_path) if csv_report_path is not None else self.report_path.with_suffix(".csv")
        )
        self.namespace = namespace or "default"

    def run(self, *, enforce: bool = True) -> dict[str, object]:
        findings = self._evaluate()
        dry_payload = [self._finding_to_dict(finding) for finding in findings]
        enforced: List[dict[str, object]] = []
        if enforce:
            enforced = [
                self._finding_to_dict(finding)
                for finding in self._enforce(findings)
            ]
        report = {
            "dry_run": dry_payload,
            "enforced": enforced,
        }
        self._write_reports(report)
        outcome = "success"
        reason = "completed"
        if not findings:
            reason = "no_action"
        self.metrics.mark_operation(
            operation="retention",
            outcome=outcome,
            reason=reason,
            namespace=self.namespace,
        )
        return report

    def _evaluate(self) -> List[RetentionFinding]:
        now = self.clock.now().timestamp()
        files = [
            {
                "path": path,
                "mtime": mtime,
                "size": size,
                "age_days": math.floor(max(0.0, (now - mtime) / 86400)),
            }
            for path, mtime, size in self._iter_files()
        ]
        files.sort(key=lambda item: item["mtime"])
        total_bytes = sum(item["size"] for item in files)
        findings: List[RetentionFinding] = []

        remaining: List[dict[str, object]] = []
        for item in files:
            if item["age_days"] > self.config.age_days:
                finding = RetentionFinding(
                    path=item["path"],
                    reason="age",
                    age_days=int(item["age_days"]),
                    size_bytes=int(item["size"]),
                )
                findings.append(finding)
                self.metrics.mark_retention(
                    mode="dry_run",
                    reason="age",
                    namespace=self.namespace,
                )
                total_bytes -= int(item["size"])
            else:
                remaining.append(item)

        if total_bytes > self.config.max_total_bytes:
            remaining.sort(key=lambda item: item["size"], reverse=True)
            for item in remaining:
                if total_bytes <= self.config.max_total_bytes:
                    break
                finding = RetentionFinding(
                    path=item["path"],
                    reason="size",
                    age_days=int(item["age_days"]),
                    size_bytes=int(item["size"]),
                )
                findings.append(finding)
                self.metrics.mark_retention(
                    mode="dry_run",
                    reason="size",
                    namespace=self.namespace,
                )
                total_bytes -= int(item["size"])
        return findings

    def _enforce(self, findings: Iterable[RetentionFinding]) -> List[RetentionFinding]:
        removed: List[RetentionFinding] = []
        for finding in findings:
            try:
                finding.path.unlink(missing_ok=True)
                removed.append(finding)
                self.metrics.mark_retention(
                    mode="enforce",
                    reason=finding.reason,
                    namespace=self.namespace,
                )
                self.logger.bind(f"retention-{finding.path.name}").info(
                    "retention.deleted",
                    path=str(finding.path),
                    reason=finding.reason,
                )
            except OSError as exc:
                self.metrics.mark_operation(
                    operation="retention",
                    outcome="failure",
                    reason="delete_failed",
                    namespace=self.namespace,
                )
                raise RuntimeError(
                    persian_error(
                        "حذف فایل در سیاست نگه‌داری شکست خورد.",
                        "RETENTION_DELETE_FAILED",
                        correlation_id=finding.path.name,
                        details=str(exc),
                    )
                )
        return removed

    def _iter_files(self) -> Iterable[tuple[Path, float, int]]:
        for root in (self.artifacts_root, self.backups_root):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                stat = path.stat()
                yield path, stat.st_mtime, stat.st_size

    def _finding_to_dict(self, finding: RetentionFinding) -> dict[str, object]:
        path_text = str(finding.path)
        if path_text.startswith(("=", "+", "-", "@")):
            path_text = "'" + path_text
        return {
            "path": path_text,
            "reason": finding.reason,
            "age_days": int(finding.age_days),
            "size_bytes": finding.size_bytes,
        }

    def _write_reports(self, report: dict[str, object]) -> None:
        atomic_write_json(self.report_path, report)
        rows: List[List[str]] = [["mode", "path", "reason", "age_days", "size_bytes"]]
        for mode in ("dry_run", "enforced"):
            for entry in report.get(mode, []):
                rows.append(
                    [
                        mode,
                        str(entry["path"]),
                        str(entry["reason"]),
                        str(entry["age_days"]),
                        str(entry["size_bytes"]),
                    ]
                )
        self._write_csv(rows)

    def _write_csv(self, rows: List[List[str]]) -> None:
        import csv

        self.csv_report_path.parent.mkdir(parents=True, exist_ok=True)
        with self.csv_report_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
            writer.writerows(rows)


__all__ = ["RetentionEnforcer", "RetentionFinding"]
