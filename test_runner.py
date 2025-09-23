#!/usr/bin/env python3
"""Lightweight wrapper to trigger adaptive testing modes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(mode: str) -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))
    cmd = [sys.executable, "-m", "scripts.adaptive_testing", "--mode", mode]
    print(f"[test-runner] executing: {' '.join(cmd)}")
    try:
        completed = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
        return completed.returncode
    except FileNotFoundError as exc:
        print(f"[test-runner] python executable not found: {exc}")
        return 127


def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive testing launcher")
    parser.add_argument("--mode", default="quick", help="Testing mode to execute")
    args = parser.parse_args()
    sys.exit(run(args.mode))


if __name__ == "__main__":
    main()
