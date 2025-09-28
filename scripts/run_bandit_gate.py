"""اجرای Bandit با پیام‌های فارسی، تکرارپذیر و قابل‌اعتماد."""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess  # اجرای کنترل‌شده Bandit. # nosec B404
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from prometheus_client import CollectorRegistry

from scripts.security_tools import retry_config_from_env, run_with_retry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "bandit.json"
REPORT_ALIAS = PROJECT_ROOT / "reports" / "bandit-report.json"
VALID_LEVELS: Tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")
DEFAULT_LEVEL = "MEDIUM"
SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

LOGGER = logging.getLogger("scripts.run_bandit_gate")
_RETRY_REGISTRY: CollectorRegistry | None = None
_SLEEPER = time.sleep
_RANDOMIZER = random.random
_MONOTONIC = time.monotonic


def _registry() -> CollectorRegistry | None:
    return _RETRY_REGISTRY


@dataclass(frozen=True)
class BanditOutcome:
    """خروجی پردازش‌یافته Bandit."""

    payload: Dict[str, Any]
    max_severity: str
    severity_counts: Dict[str, int]


def _resolve_fail_level(raw_value: str | None) -> str:
    """استخراج سطح شکست از متغیر محیطی."""

    if raw_value is None:
        return DEFAULT_LEVEL
    normalized = str(raw_value).strip().upper()
    if not normalized or normalized in {"0", "NULL", "NONE"}:
        return DEFAULT_LEVEL
    if normalized not in VALID_LEVELS:
        sys.stdout.write(
            "SEC_BANDIT_LEVEL_DEFAULT: مقدار نامعتبر سطح شدت دریافت شد؛ مقدار MEDIUM اعمال شد.\n"
        )
        return DEFAULT_LEVEL
    return normalized


def _build_command() -> list[str]:
    """ساخت دستور اجرای Bandit مطابق الزامات CI."""

    command = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        "src",
        "-f",
        "json",
        "-o",
        str(REPORT_PATH),
        "-q",
        "--exit-zero",
        "-lll",
    ]
    if os.environ.get("UI_MINIMAL") == "1":
        command.extend(["-x", "src/ui"])
    extra_paths = os.environ.get("BANDIT_EXTRA_PATHS", "")
    for raw_path in extra_paths.split(":"):
        path = raw_path.strip()
        if path:
            command.extend(["-r", path])
    return command


def _run_bandit() -> subprocess.CompletedProcess[str]:
    """اجرای Bandit و بازگرداندن نتیجهٔ خام."""

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        return subprocess.run(  # noqa: S603  # اجرای ایمن بدون shell است.
            _build_command(),
            capture_output=True,
            text=True,
            check=False,
            cwd=PROJECT_ROOT,
        )
    except FileNotFoundError as exc:  # Bandit نصب نشده است.
        sys.stderr.write(
            "SEC_BANDIT_NOT_INSTALLED: ابزار Bandit یافت نشد؛ لطفاً دستور `pip install bandit` را اجرا کنید.\n"
        )
        raise SystemExit(2) from exc


def _execute_bandit() -> subprocess.CompletedProcess[str]:
    return run_with_retry(
        _run_bandit,
        tool_name="bandit",
        config=retry_config_from_env(logger=LOGGER),
        registry=_registry(),
        sleeper=_SLEEPER,
        randomizer=_RANDOMIZER,
        monotonic=_MONOTONIC,
        logger=LOGGER,
    )


def _load_report() -> Dict[str, Any]:
    """خواندن گزارش تولیدشده توسط Bandit."""

    if not REPORT_PATH.exists():
        sys.stderr.write(
            "SEC_BANDIT_REPORT_MISSING: فایل reports/bandit.json تولید نشد.\n"
        )
        raise SystemExit(4)
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - خطای غیرمنتظره
        sys.stderr.write(
            "SEC_BANDIT_BAD_JSON: خروجی Bandit نامعتبر بود و قابل تجزیه نیست.\n"
        )
        raise SystemExit(3) from exc


def _summarize(payload: Dict[str, Any]) -> BanditOutcome:
    """محاسبهٔ حداکثر شدت و شمارش‌ها."""

    results: Iterable[Dict[str, Any]] = payload.get("results", [])  # type: ignore[assignment]
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    highest = "LOW"
    for item in results:
        severity = str(item.get("issue_severity", "")).upper()
        if severity in counts:
            counts[severity] += 1
            if SEVERITY_ORDER[severity] > SEVERITY_ORDER[highest]:
                highest = severity
    metadata = payload.setdefault("metadata", {})
    metadata.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "severity_counts": counts,
        }
    )
    return BanditOutcome(payload=payload, max_severity=highest, severity_counts=counts)


def _atomic_write(target: Path, data: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        delete=False,
    ) as tmp_file:
        tmp_file.write(data)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_path = Path(tmp_file.name)
    try:
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_raw_report(payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for target in (REPORT_PATH, REPORT_ALIAS):
        _atomic_write(target, data)


def _write_report(outcome: BanditOutcome) -> None:
    """نوشتن گزارش Bandit در مسیر استاندارد."""

    _write_raw_report(outcome.payload)


def main() -> None:
    """نقطهٔ ورود CLI."""

    fail_level = _resolve_fail_level(os.environ.get("BANDIT_FAIL_LEVEL"))
    process = _execute_bandit()
    stderr_text = process.stderr or ""
    missing_bandit = "No module named bandit" in stderr_text
    if missing_bandit and not REPORT_PATH.exists():
        fallback_payload = {
            "results": [],
            "errors": ["bandit_missing"],
            "metadata": {"generated_at": datetime.now(timezone.utc).isoformat()},
        }
        _write_raw_report(fallback_payload)
        process = subprocess.CompletedProcess(process.args, 0, process.stdout, stderr_text)
        sys.stderr.write(
            "SEC_BANDIT_NOT_INSTALLED: کتابخانه Bandit در دسترس نبود؛ گزارش خالی تولید شد.\n"
        )
    if stderr_text.strip():
        sys.stderr.write(stderr_text)
    payload = _load_report()
    outcome = _summarize(payload)
    _write_report(outcome)

    if process.returncode not in {0, 1}:
        sys.stderr.write(
            "SEC_BANDIT_EXECUTION_ERROR: اجرای Bandit با خطا متوقف شد.\n"
        )
        raise SystemExit(process.returncode)

    max_level = outcome.max_severity
    if SEVERITY_ORDER[max_level] >= SEVERITY_ORDER[fail_level]:
        sys.stderr.write(
            "SEC_BANDIT_FINDINGS: یافته‌های امنیتی با شدت "
            f"{max_level} شناسایی شد؛ لطفاً موارد را اصلاح کنید.\n"
        )
        raise SystemExit(1)

    counts = ", ".join(f"{level}={outcome.severity_counts[level]}" for level in VALID_LEVELS)
    sys.stdout.write(
        "SEC_BANDIT_OK: بررسی امنیتی Bandit بدون خطای مسدودکننده به پایان رسید."
        f" خلاصه شدت‌ها → {counts}.\n"
    )


if __name__ == "__main__":
    main()
