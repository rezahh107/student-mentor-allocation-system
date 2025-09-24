"""اجرای Bandit با خلاصه فارسی برای CI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "bandit-report.json"


def _build_command() -> list[str]:
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


def _write_report(payload: Dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    proc = subprocess.run(_build_command(), capture_output=True, text=True)
    raw_stdout = proc.stdout or ""

    try:
        parsed = json.loads(raw_stdout or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        fallback: Dict[str, Any] = {
            "وضعیت": "Bandit خروجی JSON معتبری تولید نکرد.",
            "returncode": proc.returncode,
            "stdout": raw_stdout,
            "stderr": proc.stderr or "",
        }
        _write_report(fallback)
        sys.stderr.write(f"Bandit JSON parse error: {exc}\n")
        raise SystemExit(2)

    payload: Dict[str, Any]
    if isinstance(parsed, dict):
        payload = dict(parsed)
    else:
        payload = {"bandit_payload": parsed}
    payload.setdefault("results", [])
    _write_report(payload)

    if proc.returncode not in {0, 1}:
        sys.stderr.write(raw_stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)

    results = payload.get("results", [])
    medium_high = [
        item for item in results if str(item.get("issue_severity", "")).lower() in {"medium", "high"}
    ]
    if medium_high:
        sys.stderr.write("یافته‌های امنیتی Bandit (مسدودکننده):\n")
        for issue in medium_high:
            sys.stderr.write(
                f"- {issue.get('issue_severity')} {issue.get('test_id')} "
                f"{issue.get('filename')}:{issue.get('line_number')} {issue.get('issue_text')}\n"
            )
        raise SystemExit(1)

    low_items = [item for item in results if str(item.get("issue_severity", "")).lower() == "low"]
    if low_items:
        sys.stderr.write("هشدارهای کم‌اهمیت Bandit (صرفاً اطلاع‌رسانی):\n")
        for issue in low_items:
            sys.stderr.write(
                f"- {issue.get('test_id')} {issue.get('filename')}:{issue.get('line_number')} {issue.get('issue_text')}\n"
            )
    else:
        sys.stdout.write("Bandit: بدون هشدار جدی.\n")


if __name__ == "__main__":
    main()
