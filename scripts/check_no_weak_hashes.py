"""Detect usage of weak hashing primitives with deterministic retries."""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from prometheus_client import CollectorRegistry

from scripts.security_tools import retry_config_from_env, run_with_retry

LOGGER = logging.getLogger("scripts.check_no_weak_hashes")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (PROJECT_ROOT / "src", PROJECT_ROOT / "scripts")

_RETRY_REGISTRY: CollectorRegistry | None = None
_SLEEPER = time.sleep

WEAK_CALL_PATTERNS = (
    re.compile(r"hashlib\.(md5|sha1)\s*\(", re.IGNORECASE),
    re.compile(r"hashlib\.new\(\s*(['\"])(md5|sha1)\1", re.IGNORECASE),
)
WEAK_IMPORT_PATTERN = re.compile(r"from\s+hashlib\s+import\s+.*\b(md5|sha1)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    line: str


def _registry() -> CollectorRegistry | None:
    return _RETRY_REGISTRY


def _iter_files(targets: Sequence[Path]) -> Iterator[Path]:
    for base in targets:
        if not base.exists():
            continue
        if base.is_file() and base.suffix == ".py":
            yield base
            continue
        for path in base.rglob("*.py"):
            if "tests" in path.parts:
                continue
            yield path


def _scan_file(path: Path) -> Iterable[Finding]:
    content = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    if WEAK_IMPORT_PATTERN.search(content):
        for idx, line in enumerate(content.splitlines(), start=1):
            if WEAK_IMPORT_PATTERN.search(line):
                findings.append(Finding(path=path, line_number=idx, line=line.strip()))
        return findings

    for idx, line in enumerate(content.splitlines(), start=1):
        if any(pattern.search(line) for pattern in WEAK_CALL_PATTERNS):
            findings.append(Finding(path=path, line_number=idx, line=line.strip()))
    return findings


def scan_for_weak_hashes(targets: Sequence[Path] | None = None) -> list[Finding]:
    selected = list(targets or DEFAULT_TARGETS)
    findings: list[Finding] = []
    for path in _iter_files(selected):
        findings.extend(_scan_file(path))
    return findings


def _scan_with_retry(targets: Sequence[Path]) -> list[Finding]:
    return run_with_retry(
        lambda: scan_for_weak_hashes(targets),
        tool_name="weak_hash_scan",
        config=retry_config_from_env(prefix="SEC_WEAK_HASH", logger=LOGGER),
        registry=_registry(),
        sleeper=_SLEEPER,
        logger=LOGGER,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect md5/sha1 usage in the codebase.")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional override paths to scan")
    args = parser.parse_args(argv)
    targets = args.paths or list(DEFAULT_TARGETS)
    findings = _scan_with_retry(targets)
    if findings:
        for finding in findings:
            sys.stderr.write(
                f"WEAK_HASH:{finding.path.relative_to(PROJECT_ROOT)}:{finding.line_number}:{finding.line}\n"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
