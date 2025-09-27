#!/usr/bin/env python3
"""Deterministic pytest runner for CI environments."""

from __future__ import annotations

import os
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env.setdefault("PYTHONWARNINGS", "error")
    cmd = [sys.executable, "-m", "pytest", "-W", "error", *argv]
    result = subprocess.run(cmd, env=env, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
