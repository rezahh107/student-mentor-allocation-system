"""اجرای تست‌های legacy با پوشش و خلاصه فارسی."""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess  # اجرای کنترل‌شده pytest با پوشش. # nosec B404
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

try:
    from defusedxml import ElementTree as ET  # type: ignore

    SAFE_XML_BACKEND = "defusedxml"
    SAFE_XML_FALLBACK_NOTICE = ""
except ImportError:
    import xml.etree.ElementTree as ET  # nosec B314,B405 - فقط coverage.xml محلی و تولیدشده توسط pytest خوانده می‌شود.

    SAFE_XML_BACKEND = "stdlib"
    SAFE_XML_FALLBACK_NOTICE = (
        "SEC_SAFE_XML_FALLBACK: ماژول defusedxml در دسترس نبود؛ تجزیهٔ coverage.xml"
        " محلی با ماژول استاندارد انجام شد."
    )
    sys.stderr.write(SAFE_XML_FALLBACK_NOTICE + "\n")


if SAFE_XML_BACKEND == "stdlib":

    def _safe_parse(xml_path: Path) -> ET.ElementTree:
        """تجزیهٔ پوشش با اتکا به فایل محلی تولیدشده."""

        return ET.parse(xml_path)  # nosec B314 - فایل coverage.xml فقط در همین ماشین تولید شده است.

else:

    def _safe_parse(xml_path: Path) -> ET.ElementTree:
        """تجزیهٔ پوشش با defusedxml."""

        return ET.parse(xml_path)  # nosec B314 - defusedxml حملات XXE را خنثی می‌کند.

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


ZERO_WIDTH_CHARS = {
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\ufeff",  # byte order mark
}

THRESHOLD_TRANSLATION = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "٫": ".",
        "٬": "",
    }
)


def _normalize_threshold_text(value: str) -> str:
    """پاک‌سازی و نرمال‌سازی متن آستانه برای پشتیبانی از ارقام فارسی."""

    stripped = "".join(ch for ch in value if ch not in ZERO_WIDTH_CHARS)
    translated = stripped.translate(THRESHOLD_TRANSLATION)
    return unicodedata.normalize("NFKC", translated)


def _resolve_threshold(raw_value: str | None) -> float:
    """محاسبهٔ آستانه پوشش با درنظرگرفتن مقادیر غیرعادی."""

    if raw_value is None:
        return DEFAULT_THRESHOLD
    text = _normalize_threshold_text(str(raw_value).strip())
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


def _format_threshold_for_cli(threshold: float) -> str:
    """نمایش مقدار آستانه برای استفاده در خط فرمان."""

    if threshold.is_integer():
        return str(int(threshold))
    formatted = f"{threshold:.2f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _emit_pytest_cov_missing() -> None:
    """چاپ پیام خطای نبودن افزونه pytest-cov."""

    sys.stderr.write(
        "❌ PYTEST_COV_MISSING: لطفاً بسته pytest-cov را نصب کنید.\n"
    )


def _ensure_pytest_cov() -> None:
    """بررسی در دسترس بودن افزونه pytest-cov با مدیریت خطای PluginValidationError."""

    try:
        import pytest  # type: ignore
        from _pytest.config import get_config  # type: ignore
        from _pytest.config.exceptions import PluginValidationError  # type: ignore
    except ImportError:
        try:
            __import__("pytest_cov")
        except ImportError:
            _emit_pytest_cov_missing()
            raise SystemExit(6)
        return

    try:
        __import__("pytest_cov")
    except ImportError:
        _emit_pytest_cov_missing()
        raise SystemExit(6)

    try:
        config = get_config()
        config.pluginmanager.import_plugin("pytest_cov")
    except PluginValidationError:
        _emit_pytest_cov_missing()
        raise SystemExit(6)
    except ImportError:
        _emit_pytest_cov_missing()
        raise SystemExit(6)


def _run_pytest(
    test_targets: List[str],
    extra_args: Iterable[str],
    threshold: float,
) -> subprocess.CompletedProcess[str]:
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
        "--cov-fail-under=" + _format_threshold_for_cli(threshold),
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


def _extract_pytest_cov_failure(stdout: str, stderr: str) -> tuple[float, float] | None:
    """استخراج پوشش و آستانه از پیام خطای pytest-cov."""

    pattern = re.compile(
        r"Required test coverage of\s+(?P<threshold>[0-9]+(?:\.[0-9]+)?)%\s+not reached\.\s+Total coverage:\s+(?P<percent>[0-9]+(?:\.[0-9]+)?)%",
        re.IGNORECASE,
    )
    for line in (stdout + "\n" + stderr).splitlines():
        match = pattern.search(line)
        if match:
            threshold_value = float(match.group("threshold"))
            percent_value = float(match.group("percent"))
            return percent_value, threshold_value
    return None


def _parse_coverage() -> float:
    """خواندن فایل XML پوشش و استخراج درصد کلی src."""

    if not COVERAGE_XML.exists():
        sys.stderr.write(
            "COV_XML_MISSING: فایل coverage.xml یافت نشد؛ اجرای pytest احتمالاً ناکام مانده است.\n"
        )
        raise SystemExit(4)
    tree = _safe_parse(COVERAGE_XML)
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
    _ensure_pytest_cov()
    process = _run_pytest(test_targets, extra_args, threshold)
    if process.returncode == 5:
        sys.stderr.write(
            "COV_NO_TESTS: هیچ تست legacy مطابق الگو یافت نشد.\n"
        )
        raise SystemExit(5)
    if process.returncode != 0:
        coverage_failure = _extract_pytest_cov_failure(process.stdout, process.stderr)
        if coverage_failure is not None:
            percent_value, _ = coverage_failure
            try:
                percent_from_xml = _parse_coverage()
            except SystemExit:
                percent_from_xml = percent_value
            if summary_mode:
                tail = _tail_output(process.stdout, process.stderr)
                if tail:
                    sys.stdout.write(tail + "\n")
                sys.stderr.write(
                    "Failure: ❌ COV_BELOW_THRESHOLD: پوشش %.2f%% < %.2f%%\n"
                    % (percent_from_xml, threshold)
                )
            else:
                sys.stdout.write(process.stdout)
                sys.stderr.write(process.stderr)
                sys.stderr.write(
                    "COV_BELOW_THRESHOLD: پوشش تست %.2f%% از آستانه %.2f%% کمتر است.\n"
                    % (percent_from_xml, threshold)
                )
            _ensure_html_report()
            raise SystemExit(1)
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
