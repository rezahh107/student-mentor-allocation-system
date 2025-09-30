from __future__ import annotations

"""Rollback helper for reverting the most recent commit safely.

ابزار کمکی برای بازگردانی امن آخرین تغییرات.
"""

import subprocess  # اجرای کنترل‌شده دستورات git. # nosec B404
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.logging_config import setup_logging

setup_logging()
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "rollback_events.log"


def log_rollback(message: str, *, success: bool) -> None:
    """Append rollback metadata to the audit log.

    ثبت رخداد بازگردانی در فایل گزارش جهت رهگیری.
    """

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    outcome = "SUCCESS" if success else "FAILED"
    entry = f"{timestamp} | {outcome} | {message}\n"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def rollback_changes(target: Optional[str] = "HEAD") -> int:
    """Perform a git revert --no-commit for the provided target.

    اجرای دستور git revert --no-commit برای هدف مشخص شده.
    """

    actual_target = target or "HEAD"
    cmd = ["git", "revert", "--no-commit", actual_target]
    print(f"[rollback] $ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True)  # فرمان git ثابت و بدون shell است. # nosec B603
    except FileNotFoundError as exc:
        msg = f"git executable not found: {exc}"
        print(f"[rollback] {msg}")
        log_rollback(msg, success=False)
        return 1
    except subprocess.CalledProcessError as exc:
        msg = f"git revert failed with code {exc.returncode}"
        print(f"[rollback] {msg}")
        log_rollback(msg, success=False)
        return exc.returncode or 1

    success_msg = f"Revert applied against {actual_target} without committing."
    print(f"[rollback] {success_msg}")
    log_rollback(success_msg, success=True)
    return 0


def main() -> int:
    """CLI entrypoint.

    نقطه ورود برای اجرای ابزار از خط فرمان.
    """

    return rollback_changes()


if __name__ == "__main__":
    raise SystemExit(main())
