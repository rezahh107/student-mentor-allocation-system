#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

RESERVED_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
}

WINDOW = 4


def iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            yield from (candidate for candidate in path.rglob("*.py") if candidate.is_file())
        elif path.suffix == ".py" and path.is_file():
            yield path


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    lines = text.splitlines()
    hits: list[str] = []
    for index, line in enumerate(lines):
        if "extra" not in line:
            continue
        if not re.search(r"extra\s*=", line):
            continue
        snippet = "\n".join(lines[max(0, index - 1) : min(len(lines), index + WINDOW)])
        for key in RESERVED_KEYS:
            pattern = rf"['\"]{re.escape(key)}['\"]"
            if re.search(pattern, snippet):
                hits.append(f"{path}:{index + 1}: reserved key '{key}' in logging extra")
    return hits


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check logging extra dictionaries for reserved keys")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path.cwd()])
    args = parser.parse_args(argv)

    findings: list[str] = []
    for candidate in iter_python_files(args.paths or [Path.cwd()]):
        findings.extend(scan_file(candidate))

    if findings:
        for line in findings:
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
