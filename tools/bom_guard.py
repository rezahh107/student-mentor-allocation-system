"""Detect UTF-8 BOM markers within the repository tree."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

BOM = "\ufeff".encode("utf-8")
TARGET_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".toml",
    ".yml",
    ".yaml",
    ".ini",
    ".json",
})
SKIP_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        "build",
        "dist",
        "logs",
        "tmp",
        "tmpfile",
        "pip-wheel-metadata",
    }
)
_EVIDENCE = "AGENTS.md::Determinism & CI"


@dataclass(slots=True)
class Finding:
    """Represents a BOM occurrence for deterministic reporting."""

    path: Path
    category: str

    def to_payload(self) -> dict[str, str]:
        """Return a JSON-ready payload describing the BOM finding."""
        return {"path": str(self.path), "category": self.category, "evidence": _EVIDENCE}


def _iter_candidate_files(paths: Sequence[Path]) -> Iterable[Path]:
    for root in paths:
        if root.is_file():
            if root.suffix.lower() in TARGET_EXTENSIONS:
                yield root
            continue
        if root.name in SKIP_DIRECTORIES:
            continue
        for candidate in root.iterdir():
            if candidate.is_symlink():
                continue
            if candidate.is_dir() and candidate.name in SKIP_DIRECTORIES:
                continue
            if candidate.is_dir():
                yield from _iter_candidate_files([candidate])
            elif candidate.is_file() and candidate.suffix.lower() in TARGET_EXTENSIONS:
                yield candidate


def _has_bom(path: Path) -> bool:
    with path.open("rb") as handle:
        prefix = handle.read(len(BOM))
    return prefix == BOM


def _collect_findings(paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for candidate in _iter_candidate_files(paths):
        if _has_bom(candidate):
            findings.append(Finding(path=candidate, category="utf8-bom"))
    return findings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths",
        nargs="*",
        type=Path,
        default=None,
        help="Optional subset of paths to inspect in addition to the project root.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit findings as a JSON object for machine-readable diagnostics.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Scan the repository tree and fail if a BOM is discovered."""
    argv = argv or sys.argv[1:]
    args = _parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    targets = [root]
    if args.paths:
        targets.extend(args.paths)
    findings = _collect_findings(targets)
    if findings:
        payload = [finding.to_payload() for finding in findings]
        message = json.dumps({"bom_findings": payload, "evidence": _EVIDENCE}, ensure_ascii=False)
        if args.json:
            print(message)
        else:
            print(message)
        return 1
    if args.json:
        print(json.dumps({"bom_findings": [], "evidence": _EVIDENCE}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    sys.exit(main())
