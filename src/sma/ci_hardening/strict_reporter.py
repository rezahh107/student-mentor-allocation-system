"""Strict Scoring v2 reporter used to audit pytest output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_SUMMARY_PATTERN = re.compile(
    r"=\s*(?P<passed>\d+)\s+passed,\s*"
    r"(?P<failed>\d+)\s+failed,\s*"
    r"(?P<xfailed>\d+)\s+xfailed,\s*"
    r"(?P<skipped>\d+)\s+skipped,\s*"
    r"(?P<warnings>\d+)\s+warnings"
)


@dataclass(frozen=True)
class PytestSummary:
    """Represents the high-level pytest summary counts."""

    passed: int
    failed: int
    xfailed: int
    skipped: int
    warnings: int

    @property
    def has_failures(self) -> bool:
        return any(value > 0 for value in (self.failed,))


class StrictScoringError(RuntimeError):
    """Raised when parsing or validation fails."""


def parse_summary(text: str) -> PytestSummary:
    """Parse a pytest summary string.

    Args:
        text: Raw summary text.

    Returns:
        ``PytestSummary`` extracted from the text.

    Raises:
        StrictScoringError: If parsing fails.
    """

    match = _SUMMARY_PATTERN.search(text)
    if not match:
        raise StrictScoringError("خلاصهٔ pytest نامعتبر است.")
    data = {key: int(value) for key, value in match.groupdict().items()}
    return PytestSummary(**data)


def load_summary(path: Path) -> PytestSummary:
    """Load and parse a summary file."""

    if not path.is_file():
        raise StrictScoringError("فایل خلاصهٔ pytest یافت نشد.")
    return parse_summary(path.read_text(encoding="utf-8"))


def enforce_caps(summary: PytestSummary) -> Mapping[str, int]:
    """Return cap reasons based on the summary counts."""

    caps: dict[str, int] = {}
    if summary.warnings:
        caps["warnings"] = 90
    if summary.skipped or summary.xfailed:
        caps["skip_xfail"] = 92
    if summary.failed:
        caps["failures"] = 0
    return caps


__all__ = [
    "PytestSummary",
    "StrictScoringError",
    "enforce_caps",
    "load_summary",
    "parse_summary",
]
