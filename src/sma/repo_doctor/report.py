from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass(slots=True)
class DoctorRunReport:
    name: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def add_finding(self, **data: Any) -> None:
        self.findings.append(data)

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


SUMMARY_PATTERN = re.compile(
    r"= (?P<passed>\d+) passed, (?P<failed>\d+) failed, (?P<xfailed>\d+) xfailed, (?P<skipped>\d+) skipped, (?P<warnings>\d+) warnings"
)


def parse_pytest_summary(text: str) -> Dict[str, int]:
    match = SUMMARY_PATTERN.search(text)
    if not match:
        raise ValueError("Pytest summary not found")
    return {key: int(value) for key, value in match.groupdict().items()}


__all__ = ["DoctorRunReport", "parse_pytest_summary"]
