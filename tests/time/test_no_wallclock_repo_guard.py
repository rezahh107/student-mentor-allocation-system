from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_guard(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/guards/wallclock_repo_guard.py", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_forbid_datetime_now_and_time_time(tmp_path: Path, clock_test_context):
    namespace = clock_test_context["namespace"].replace(":", "_")
    sample = tmp_path / f"{namespace}.py"
    sample.write_text(
        "from datetime import datetime\n"
        "def bad():\n"
        "    return datetime.now()\n",
        encoding="utf-8",
    )

    result = clock_test_context["retry"](lambda: _run_guard(sample))
    debug = clock_test_context["get_debug_context"]()

    assert result.returncode != 0, f"Guard must fail; context={debug} stdout={result.stdout}"
    assert "استفاده از ساعت سیستم ممنوع است" in result.stdout, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["path"].endswith(f"{namespace}.py")
    clock_test_context["cleanup_log"].append(str(sample))
