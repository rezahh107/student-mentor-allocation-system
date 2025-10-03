"""Structural validation checks for src-layout hygiene."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

RESERVED_NAMES = {
    "logging",
    "json",
    "asyncio",
    "time",
    "typing",
    "statistics",
    "secrets",
    "dataclasses",
    "pathlib",
    "email",
    "http",
    "random",
    "uuid",
    "contextlib",
    "functools",
    "operator",
    "tempfile",
    "sqlite3",
    "importlib",
    "re",
    "io",
    "math",
    "csv",
    "gzip",
    "base64",
    "hashlib",
}

ROOT = Path(__file__).resolve().parents[1] / "src"


def iter_package_dirs(root: Path) -> list[Path]:
    packages: list[Path] = []
    for path in root.rglob("*.py"):
        if path.name == "__init__.py":
            packages.append(path.parent)
    return packages


def assert_init_files() -> list[str]:
    errors: list[str] = []
    for directory in sorted({p.parent for p in ROOT.rglob("*.py")}):
        if directory.name.startswith("."):
            continue
        if (directory / "__init__.py").exists():
            continue
        errors.append(f"Missing __init__.py: {directory.relative_to(ROOT.parent)}")
    return errors


def detect_stdlib_shadowing() -> list[str]:
    problems: list[str] = []
    for package_dir in iter_package_dirs(ROOT):
        name = package_dir.name
        if name in RESERVED_NAMES:
            problems.append(
                f"Stdlib shadowing detected: {package_dir.relative_to(ROOT.parent)}"
            )
    return problems


def detect_case_conflicts() -> list[str]:
    issues: list[str] = []
    seen: dict[tuple[Path, str], Path] = {}
    for directory in sorted({p.parent for p in ROOT.rglob("*.py")}):
        key = (directory.parent, directory.name.casefold())
        if key in seen and seen[key] != directory:
            issues.append(
                "Case conflict between "
                f"{seen[key].relative_to(ROOT.parent)} and {directory.relative_to(ROOT.parent)}"
            )
        else:
            seen[key] = directory
    return issues


def detect_duplicate_packages() -> list[str]:
    tracker: defaultdict[str, list[Path]] = defaultdict(list)
    for package_dir in iter_package_dirs(ROOT):
        relative = package_dir.relative_to(ROOT)
        tracker[str(relative)].append(package_dir)
    duplicates: list[str] = []
    for rel, paths in tracker.items():
        if len(paths) > 1:
            joined = ", ".join(str(p.relative_to(ROOT.parent)) for p in paths)
            duplicates.append(f"Duplicate package path {rel}: {joined}")
    return duplicates


def main() -> int:
    failures: list[str] = []
    failures.extend(assert_init_files())
    failures.extend(detect_stdlib_shadowing())
    failures.extend(detect_case_conflicts())
    failures.extend(detect_duplicate_packages())

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("Structure validation passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution
    sys.exit(main())
