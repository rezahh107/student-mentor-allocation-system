from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_pytest_collects_cleanly() -> None:
    if os.getenv("PYTEST_INVOKED_FROM_FULL_SUITE") == "1":
        return

    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env["PYTEST_INVOKED_FROM_FULL_SUITE"] = "1"
    repo_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    context = {
        "returncode": result.returncode,
        "stdout": result.stdout[-1000:],
        "stderr": result.stderr[-1000:],
    }
    assert result.returncode == 0, context
