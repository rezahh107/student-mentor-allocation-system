from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER_PATTERN = re.compile(r"^\[(PASS|FAIL|FIXED|SKIP)\]\s+(?P<step>[^:]+)::(?P<detail>.+)$")


def parse_lines(lines: list[str]) -> dict[str, list[dict[str, str]]]:
    summary: dict[str, list[dict[str, str]]] = {"PASS": [], "FAIL": [], "FIXED": [], "SKIP": []}
    for idx, raw in enumerate(lines, start=1):
        match = MARKER_PATTERN.match(raw.strip())
        if not match:
            continue
        entry = {"line": idx, "step": match.group("step"), "detail": match.group("detail").strip()}
        summary[match.group(1)].append(entry)
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Parse installer markers from stdout and fail on [FAIL] entries.")
    parser.add_argument("input", nargs="?", help="Path to installer log. Reads stdin when omitted.")
    parser.add_argument("--json", dest="json_output", help="Optional path to write a JSON summary.")
    args = parser.parse_args(argv)

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    lines = text.splitlines()
    summary = parse_lines(lines)

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    failures = summary["FAIL"]
    if failures:
        sys.stderr.write("Detected [FAIL] markers:\n")
        for entry in failures:
            sys.stderr.write(f"  line {entry['line']}: {entry['step']} :: {entry['detail']}\n")
        return 1

    if not any(summary.values()):
        sys.stderr.write("No markers detected in installer output.\n")
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
