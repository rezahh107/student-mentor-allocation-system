#!/usr/bin/env python
"""Parse pytest summaries and enforce quality gates."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping

import typer

SUMMARY_RE = re.compile(
    r"=\s+(?P<passed>\d+)\s+passed,\s+(?P<failed>\d+)\s+failed,\s+"
    r"(?P<xfailed>\d+)\s+xfailed,\s+(?P<skipped>\d+)\s+skipped,\s+(?P<warnings>\d+)\s+warnings"
)

app = typer.Typer(help="Parse pytest summary output")


def parse_summary(text: str) -> Mapping[str, int]:
    match = SUMMARY_RE.search(text.strip())
    if not match:
        raise ValueError("invalid summary format")
    return {key: int(match.group(key)) for key in match.groupdict()}


def validate_evidence(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):  # pragma: no cover - defensive
        raise ValueError("evidence must be a mapping")
    for key, value in data.items():
        if not value:
            raise ValueError(f"missing evidence for {key}")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"invalid evidence entries for {key}")


@app.command()
def main(
    summary: str | None = typer.Option(None, "--summary", help="Raw summary text"),
    summary_file: Path | None = typer.Option(None, "--summary-file", help="Path to summary file"),
    evidence_map: Path | None = typer.Option(None, "--evidence-map", help="Evidence mapping JSON"),
) -> None:
    if summary_file is not None:
        summary_text = summary_file.read_text(encoding="utf-8")
    elif summary is not None:
        summary_text = summary
    else:
        summary_text = sys.stdin.read()
    counts = parse_summary(summary_text)
    typer.echo(json.dumps(counts, ensure_ascii=False))
    if counts.get("warnings", 0) != 0:
        raise typer.Exit(code=2)
    if evidence_map is not None:
        validate_evidence(evidence_map)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()
