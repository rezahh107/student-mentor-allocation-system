from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .fs_atomic import atomic_writer


FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass
class AuditFinding:
    provider: str
    severity: str
    message: str
    automation: str = ""
    status: str = "PASS"
    remediation: str | None = None

    def to_row(self) -> dict[str, str]:
        return {
            "automation": self.automation,
            "status": self.status,
            "provider": self.provider,
            "severity": self.severity,
            "message": self.message,
            "remediation": (self.remediation or ""),
        }


class CSVSafeWriter:
    def __init__(self, path: Path, headers: List[str]):
        self.path = path
        self.headers = headers

    def write(self, rows: Iterable[dict[str, str]]) -> None:
        with atomic_writer(self.path, encoding="utf-8", mode="w") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=self.headers,
                quoting=csv.QUOTE_ALL,
                extrasaction="ignore",
                lineterminator="\r\n",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: self._guard(value) for key, value in row.items()})

    @staticmethod
    def _guard(value: str | None) -> str:
        if value is None:
            return ""
        text = str(value)
        if text and text[0] in FORMULA_PREFIXES:
            return "'" + text
        return text


def render_markdown(findings: Iterable[AuditFinding]) -> str:
    lines = [
        "| Automation | Status | Provider | Severity | Message | Remediation |",
        "|---|---|---|---|---|---|",
    ]
    for finding in findings:
        lines.append(
            "| {automation} | {status} | {provider} | {severity} | {message} | {remediation} |".format(
                automation=finding.automation or "-",
                status=finding.status,
                provider=finding.provider,
                severity=finding.severity,
                message=finding.message,
                remediation=finding.remediation or "-",
            )
        )
    return "\n".join(lines)
