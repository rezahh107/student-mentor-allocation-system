"""Static analysis to guard against fragile relative imports in phase6_import_to_sabt."""

from __future__ import annotations

from pathlib import Path
import re
from typing import List, Tuple

TARGET_PACKAGE = "phase6_import_to_sabt"
RELATIVE_PATTERN = re.compile(r"^from\s+\.+")
SRC_PATTERN = re.compile(r"\bfrom\s+src\.|\bimport\s+src\b")


def _iter_python_files() -> List[Path]:
    package_root = Path(__file__).resolve().parents[1] / "src" / TARGET_PACKAGE
    return sorted(package_root.rglob("*.py"))


def _scan_file(path: Path) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    relative_hits: List[Tuple[int, str]] = []
    src_hits: List[Tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if RELATIVE_PATTERN.match(stripped):
            relative_hits.append((lineno, stripped))
        if SRC_PATTERN.search(line):
            src_hits.append((lineno, stripped))
    return relative_hits, src_hits


def test_phase6_imports_are_absolute() -> None:
    offenders: List[Tuple[Path, List[Tuple[int, str]]]] = []
    src_offenders: List[Tuple[Path, List[Tuple[int, str]]]] = []
    for path in _iter_python_files():
        relative_hits, src_hits = _scan_file(path)
        if relative_hits:
            offenders.append((path, relative_hits))
        if src_hits:
            src_offenders.append((path, src_hits))
    assert not offenders, {
        "package": TARGET_PACKAGE,
        "violations": [
            {
                "file": str(path.relative_to(Path(__file__).resolve().parents[1])),
                "lines": hits,
            }
            for path, hits in offenders
        ],
    }
    assert not src_offenders, {
        "package": TARGET_PACKAGE,
        "violations": [
            {
                "file": str(path.relative_to(Path(__file__).resolve().parents[1])),
                "lines": hits,
            }
            for path, hits in src_offenders
        ],
    }
