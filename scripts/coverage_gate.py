"""اجرای تست‌های legacy با پوشش و خلاصه فارسی."""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess  # اجرای کنترل‌شده pytest با پوشش. # nosec B404
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COVERAGE_XML = PROJECT_ROOT / "coverage.xml"
DEFAULT_THRESHOLD = 95.0
LEGACY_PATTERN_ENV = "LEGACY_TEST_PATTERN"
TAIL_LINE_LIMIT = 200


@dataclass(frozen=True)
class CoverageResult:
    """نگه‌دارندهٔ نتیجهٔ پوشش."""

    percent: float
    threshold: float


def _resolve_threshold(raw_value: str | None) -> float:
    """محاسبهٔ آستانه پوشش با درنظرگرفتن مقادیر غیرعادی."""

    if raw_value is None:
        return DEFAULT_THRESHOLD
    text = str(raw_value).strip()
    normalized = text.casefold()
    if not text or normalized in {"null", "none", ""}:
        return DEFAULT_THRESHOLD
    if normalized == "0":
        return 0.0
    try:
        value = float(text)
    except ValueError:
        sys.stdout.write(
            "COV_THRESHOLD_DEFAULT: مقدار آستانه نامعتبر بود و مقدار 95 اعمال شد.\n"
        )
        return DEFAULT_THRESHOLD
    if value < 0:
        return DEFAULT_THRESHOLD
    if value > 100:
        return 100.0
    return value


def _discover_tests() -> List[str]:
    """کشف تست‌های legacy بر اساس الگوی مشخص شده."""

    pattern = os.environ.get(LEGACY_PATTERN_ENV, "tests/legacy/test_*.py")
    if not pattern or pattern.strip() in {"", "0"}:
        pattern = "tests/legacy/test_*.py"
    matches = sorted(str(path) for path in PROJECT_ROOT.glob(pattern))
    if not matches:
        fallback = PROJECT_ROOT / "tests" / "legacy"
        if fallback.exists():
            return [str(fallback)]
    return matches if matches else ["tests"]


def _run_pytest(test_targets: List[str], extra_args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    """اجرای pytest با تنظیمات پوشش."""

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pytest_cov",
        "--cov=src",
        "--cov-report=term",
        "--cov-report=xml",
        "--cov-report=html",
        "--maxfail=1",
        "-q",
    ]
    command.extend(str(item) for item in extra_args)
    command.extend(test_targets)
    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return subprocess.run(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def _parse_coverage() -> float:
    """خواندن فایل XML پوشش و استخراج درصد کلی src."""

    if not COVERAGE_XML.exists():
        sys.stderr.write(
            "COV_XML_MISSING: فایل coverage.xml یافت نشد؛ اجرای pytest احتمالاً ناکام مانده است.\n"
        )
        raise SystemExit(4)
    tree = ET.parse(COVERAGE_XML)
    root = tree.getroot()
    line_rate = root.get("line-rate") or "0"
    try:
        return float(line_rate) * 100
    except ValueError as exc:  # pragma: no cover - حالت غیرمنتظره
        sys.stderr.write(
            "COV_XML_INVALID: مقدار line-rate نامعتبر است.\n"
        )
        raise SystemExit(5) from exc


def _threshold_passed(result: CoverageResult) -> bool:
    """ارزیابی عبور پوشش از آستانه."""

    return result.percent + 1e-9 >= result.threshold


def _summarize_pytest_output(stdout: str, stderr: str) -> str:
    """استخراج یک خط خلاصه از خروجی pytest."""

    lines = [line.strip() for line in stdout.splitlines() + stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in ("passed", "failed", "error", "skipped")):
            return line
    return "هیچ خلاصه‌ای از pytest یافت نشد"


def _tail_output(stdout: str, stderr: str, limit: int = TAIL_LINE_LIMIT) -> str:
    """استخراج انتهای خروجی pytest برای حالت خلاصه."""

    combined = stdout.splitlines() + stderr.splitlines()
    if not combined:
        return ""
    tail = combined[-limit:]
    return "\n".join(tail)


def _ensure_html_report() -> None:
    """اطمینان از وجود گزارش HTML برای بارگذاری در CI."""

    html_dir = PROJECT_ROOT / "htmlcov"
    if not html_dir.exists():
        sys.stderr.write(
            "COV_HTML_MISSING: دایرکتوری گزارش htmlcov تولید نشد؛ گزینه --cov-report=html را بررسی کنید.\n"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="اجرای درگاه پوشش با خلاصه فارسی")
    parser.add_argument("targets", nargs="*", help="مسیر یا الگو برای pytest")
    parser.add_argument(
        "--pytest-args",
        default="",
        help="رشته‌ای از آرگومان‌های اضافی pytest (با نقل‌قول).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="چاپ خروجی خلاصه‌شده (یک خط) با برش انتهایی در خطا.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """اجرای کامل درگاه پوشش."""

    args = _parse_args(argv or sys.argv[1:])
    threshold = _resolve_threshold(os.environ.get("COV_MIN"))
    extra_args = shlex.split(args.pytest_args)
    summary_mode = bool(args.summary)
    if args.targets:
        test_targets = args.targets
    else:
        test_targets = _discover_tests()
    process = _run_pytest(test_targets, extra_args)
    if process.returncode == 5:
        sys.stderr.write(
            "COV_NO_TESTS: هیچ تست legacy مطابق الگو یافت نشد.\n"
        )
        raise SystemExit(5)
    if process.returncode != 0:
        if summary_mode:
            tail = _tail_output(process.stdout, process.stderr)
            if tail:
                sys.stdout.write(tail + "\n")
            sys.stderr.write(
                f"Failure: ❌ PYTEST_FAILED: اجرای pytest با کد {process.returncode} متوقف شد.\n"
            )
        else:
            sys.stdout.write(process.stdout)
            sys.stderr.write(process.stderr)
        raise SystemExit(process.returncode)

    if not summary_mode:
        summary_line = _summarize_pytest_output(process.stdout, process.stderr)
        sys.stdout.write(f"COV_PYTEST_SUMMARY: {summary_line}\n")

    percent = _parse_coverage()
    result = CoverageResult(percent=percent, threshold=threshold)

    passed = _threshold_passed(result)
    if summary_mode:
        if not passed:
            tail = _tail_output(process.stdout, process.stderr)
            if tail:
                sys.stdout.write(tail + "\n")
            sys.stderr.write(
                "Failure: ❌ COV_BELOW_THRESHOLD: پوشش %.2f%% < %.2f%%\n"
                % (result.percent, result.threshold)
            )
            raise SystemExit(1)
        sys.stdout.write(
            "Success: ✅ پوشش تست‌ها عبور کرد: %.2f%% ≥ %.2f%%\n"
            % (result.percent, result.threshold)
        )
    else:
        if not passed:
            sys.stderr.write(
                "COV_BELOW_THRESHOLD: پوشش تست %.2f%% از آستانه %.2f%% کمتر است.\n"
                % (result.percent, result.threshold)
            )
            raise SystemExit(1)
        sys.stdout.write(
            "COV_THRESHOLD_OK: پوشش تست %.2f%% با آستانه %.2f%% منطبق است.\n"
            % (result.percent, result.threshold)
        )
    _ensure_html_report()


if __name__ == "__main__":
    main()
