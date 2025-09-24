"""تضمین می‌کند پیکربندی Bandit فقط خطاهای مهم را مسدود کند."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _build_bandit_cmd() -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        "src",
        "scripts",
        "-f",
        "json",
        "-q",
        "-c",
        str(PROJECT_ROOT / ".bandit"),
    ]
    if os.environ.get("UI_MINIMAL") == "1":
        cmd.extend(["-x", "src/ui"])
    return cmd

def test_bandit_medium_high_blocked() -> None:
    """Bandit must not report Medium/High severities."""

    proc = subprocess.run(
        _build_bandit_cmd(),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in {0, 1}, proc.stderr
    payload = json.loads(proc.stdout or "{}")
    findings: Iterable[dict[str, object]] = payload.get("results", [])
    medium_high = [
        issue
        for issue in findings
        if str(issue.get("issue_severity", "")).lower() in {"medium", "high"}
    ]
    lows = [
        issue
        for issue in findings
        if str(issue.get("issue_severity", "")).lower() == "low"
    ]

    if medium_high:
        formatted = ", ".join(
            f"{item.get('test_id')}:{item.get('filename')}:{item.get('line_number')}"
            for item in medium_high
        )
        pytest.fail(f"Bandit مسدودکننده یافت شد: {formatted}")

    # چاپ هشدارهای کم‌اهمیت برای عیب‌یابی CI بدون شکست.
    for issue in lows:
        sys.stdout.write(
            f"[Bandit-low] {issue.get('test_id')} {issue.get('filename')}:{issue.get('line_number')}\n"
        )


def test_no_silent_exception_pass() -> None:
    """هیچ الگوی try/except/pass در کدهای اصلی باقی نماند."""

    pattern = re.compile(r"except\s+Exception\s*:\s*pass")
    for base in ("src", "scripts"):
        for path in (PROJECT_ROOT / base).rglob("*.py"):
            if "tests" in path.parts:
                continue
            content = path.read_text(encoding="utf-8")
            assert not pattern.search(content), f"الگوی غیرفعال در {path}"  # nosec B110


def test_bandit_report_artifact_written() -> None:
    """اجرای دروازه باید گزارش JSON را همیشه بنویسد."""

    report_path = PROJECT_ROOT / "reports" / "bandit-report.json"
    if report_path.exists():
        report_path.unlink()

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.run_bandit_gate"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert report_path.exists(), "فایل گزارش Bandit تولید نشد."
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "results" in payload
