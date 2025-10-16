#!/usr/bin/env python3
"""Repository guard preventing direct wall-clock usage and invalid timezones."""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from prometheus_client import CollectorRegistry, Counter, generate_latest

FORBIDDEN_CALLS: Sequence[tuple[str, ...]] = (
    ("datetime", "now"),
    ("datetime", "datetime", "now"),
    ("time", "time"),
    ("date", "today"),
    ("pandas", "Timestamp", "now"),
)
BANNED_TZ = "Asia/Baku"
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "fakeredis",
    "tmpfile",
}
ALLOWED_EXTENSIONS = {".py"}
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 0.05
ALLOWLIST_SENTINEL = "# WALLCLOCK_ALLOW"
ALLOWLIST_DIRECTORIES = {"scripts", "migrations"}
TEST_DIRECTORY = "tests"
BANNED_TZ_ALLOWED_PREFIX = ("tools", "guards")


@dataclass(slots=True)
class Violation:
    path: Path
    line: int
    message: str
    suggestion: str
    rule: str
    snippet: str


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def _should_skip(path: Path, *, root: Path) -> bool:
    relative = _relative_to(path, root)
    parts: Iterable[str]
    if relative is None:
        parts = path.parts
    else:
        parts = relative.parts
    return any(part in EXCLUDED_PARTS for part in parts)


def _iter_python_files(paths: Sequence[Path], *, root: Path) -> Iterator[Path]:
    for base in paths:
        candidate = base.resolve()
        if not candidate.exists():
            continue
        if candidate.is_file():
            if candidate.suffix in ALLOWED_EXTENSIONS and not _should_skip(candidate, root=root):
                yield candidate
            continue
        for file in sorted(candidate.rglob("*.py")):
            if _should_skip(file, root=root):
                continue
            yield file.resolve()


def _load_source(path: Path) -> str:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            if attempt == RETRY_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError("UNREACHABLE")


def _node_path(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.insert(0, current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.insert(0, current.id)
    return tuple(parts)


def _has_allow_sentinel(source: str) -> bool:
    return ALLOWLIST_SENTINEL in source


def _is_wallclock_allowlisted(path: Path, *, root: Path, source: str) -> bool:
    relative = _relative_to(path, root)
    if relative is None:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] == TEST_DIRECTORY:
        return True
    if parts[0] in ALLOWLIST_DIRECTORIES:
        return True
    if parts[0] == "tools" and _has_allow_sentinel(source):
        return True
    return _has_allow_sentinel(source)


def _is_timezone_allowlisted(path: Path, *, root: Path) -> bool:
    relative = _relative_to(path, root)
    if relative is None:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] == "docs":
        return True
    if len(parts) >= 2 and parts[0] == BANNED_TZ_ALLOWED_PREFIX[0] and parts[1] == BANNED_TZ_ALLOWED_PREFIX[1]:
        return True
    return False


def _check_ast(
    path: Path,
    tree: ast.AST,
    source_lines: list[str],
    *,
    allow_wallclock: bool,
    allow_timezone: bool,
) -> Iterator[Violation]:
    if not allow_wallclock:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_path = _node_path(node.func)
                if call_path in FORBIDDEN_CALLS:
                    line = getattr(node, "lineno", 0)
                    snippet = source_lines[line - 1].strip() if 0 < line <= len(source_lines) else ""
                    yield Violation(
                        path=path,
                        line=line,
                        message="استفاده از ساعت سیستم ممنوع است: از Clock تزریق‌شده استفاده کنید.",
                        suggestion="تابع ensure_clock(...) را برای تامین Clock به‌کار ببرید.",
                        rule="wallclock",
                        snippet=snippet,
                    )
    if not allow_timezone:
        for idx, text in enumerate(source_lines, start=1):
            if BANNED_TZ in text:
                yield Violation(
                    path=path,
                    line=idx,
                    message=f"منطقهٔ زمانی مجاز فقط Asia/Tehran است؛ مقدار یافت‌شده: {BANNED_TZ}",
                    suggestion="همهٔ مناطق زمانی را به Asia/Tehran یکسان‌سازی کنید.",
                    rule="timezone",
                    snippet=text.strip(),
                )


def _gather_targets(args: argparse.Namespace, *, root: Path) -> Sequence[Path]:
    if args.paths:
        return [Path(p).resolve() for p in args.paths]
    defaults = [root / "src", root / "tools"]
    return [candidate.resolve() for candidate in defaults if candidate.exists()]


def _ensure_agents_file(root: Path) -> None:
    if not (root / "AGENTS.md").exists():
        raise SystemExit("پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید.")


def _setup_metrics() -> Counter:
    registry = CollectorRegistry()
    counter = Counter(
        "repo_guard_wallclock_violations_total",
        "Total number of wall-clock usage violations detected",
        registry=registry,
    )
    globals()["_metrics_registry"] = registry
    return counter


def scan_for_violations(targets: Sequence[Path], *, root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for file in _iter_python_files(targets, root=root):
        source = _load_source(file)
        try:
            tree = ast.parse(source, filename=str(file))
        except SyntaxError:
            continue
        lines = source.splitlines()
        allow_wallclock = _is_wallclock_allowlisted(file, root=root, source=source)
        allow_timezone = _is_timezone_allowlisted(file, root=root)
        violations.extend(
            _check_ast(
                file,
                tree,
                lines,
                allow_wallclock=allow_wallclock,
                allow_timezone=allow_timezone,
            )
        )
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect forbidden wall-clock usage.")
    parser.add_argument("paths", nargs="*", help="Files or directories to scan")
    parser.add_argument("--print-metrics", action="store_true", help="Emit Prometheus metrics")
    args = parser.parse_args(argv)

    root = Path.cwd()
    _ensure_agents_file(root)
    targets = _gather_targets(args, root=root)
    counter = _setup_metrics()
    correlation_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4()))

    violations = scan_for_violations(targets, root=root)

    exit_code = 0
    if violations:
        exit_code = 1
        for violation in violations:
            counter.inc()
            payload = {
                "correlation_id": correlation_id,
                "path": str(violation.path),
                "line": violation.line,
                "message": violation.message,
                "suggestion": violation.suggestion,
                "rule": violation.rule,
                "snippet": violation.snippet,
            }
            print(json.dumps(payload, ensure_ascii=False))

    if args.print_metrics:
        registry = globals().get("_metrics_registry")
        if registry is not None:
            print(generate_latest(registry).decode("utf-8"))

    return exit_code


__all__ = ["Violation", "scan_for_violations", "main"]


if __name__ == "__main__":
    sys.exit(main())
