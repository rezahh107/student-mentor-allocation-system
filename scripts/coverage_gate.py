"""اجرای درگاه پوشش legacy با خلاصه فارسی و کنترل خروجی."""
from __future__ import annotations

import argparse
import os
import re
import selectors
import shlex
import subprocess  # اجرای کنترل‌شده pytest با پوشش. # nosec B404
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

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
TAIL_LINE_LIMIT_ENV = "COV_TAIL_LINES"
CAPTURE_CHAR_LIMIT_ENV = "COV_CAPTURE_CHAR_LIMIT"
DEFAULT_CAPTURE_CHAR_LIMIT = 200_000
SUMMARY_PREFIX_SUCCESS = "✅"
SUMMARY_PREFIX_FAILURE = "❌"


@dataclass(frozen=True)
class CoverageResult:
    """نگه‌دارندهٔ نتیجهٔ پوشش."""

    percent: float
    threshold: float


@dataclass(frozen=True)
class PytestRun:
    """نتیجهٔ اجرای pytest همراه با خروجی محدود."""

    returncode: int
    stdout: str
    stderr: str
    tail_lines: tuple[str, ...]
    summary_candidates: tuple[str, ...]
    coverage_failure: tuple[float, float] | None
    text_coverage_percent: float | None


class BoundedBuffer:
    """نگه‌داری رشته با سقف کاراکتر برای جلوگیری از مصرف حافظه."""

    def __init__(self, max_chars: int) -> None:
        self._max_chars = max_chars
        self._chunks: deque[str] = deque()
        self._length = 0

    def append(self, chunk: str) -> None:
        """افزودن رشته و حذف سرریز."""

        if not chunk:
            return
        self._chunks.append(chunk)
        self._length += len(chunk)
        while self._length > self._max_chars and self._chunks:
            removed = self._chunks.popleft()
            self._length -= len(removed)

    def getvalue(self) -> str:
        """بازگردانی خروجی محدود."""

        return "".join(self._chunks)


class StreamCollector:
    """مدیریت جریان خروجی pytest با برش انتهایی و استخراج درصد پوشش."""

    _COVERAGE_PATTERNS = (
        re.compile(r"TOTAL\s+\d+\s+\d+\s+(?P<percent>[0-9]+(?:\.[0-9]+)?)%"),
        re.compile(r"(?P<percent>[0-9]+(?:\.[0-9]+)?)%\s+TOTAL", re.IGNORECASE),
        re.compile(r"coverage:\s*(?P<percent>[0-9]+(?:\.[0-9]+)?)%", re.IGNORECASE),
    )

    _COVERAGE_FAILURE_PATTERN = re.compile(
        r"Required test coverage of\s+(?P<threshold>[0-9]+(?:\.[0-9]+)?)%\s+not reached\.\s+Total coverage:\s+(?P<percent>[0-9]+(?:\.[0-9]+)?)%",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        tail_limit: int,
        capture_char_limit: int,
        echo_stdout: bool,
        echo_stderr: bool,
    ) -> None:
        self._stdout_buffer = BoundedBuffer(capture_char_limit)
        self._stderr_buffer = BoundedBuffer(capture_char_limit)
        self._tail = deque[str](maxlen=tail_limit)
        self._summary_candidates = deque[str](maxlen=max(4, tail_limit))
        self._coverage_failure: tuple[float, float] | None = None
        self._coverage_percent: float | None = None
        self._echo_stdout = echo_stdout
        self._echo_stderr = echo_stderr

    def consume(self, text: str, stream_name: str) -> None:
        """مصرف یک chunk و به‌روزرسانی ساختارهای کمکی."""

        if not text:
            return
        target = sys.stdout if stream_name == "stdout" else sys.stderr
        if stream_name == "stdout":
            self._stdout_buffer.append(text)
            if self._echo_stdout:
                target.write(text)
                target.flush()
        else:
            self._stderr_buffer.append(text)
            if self._echo_stderr:
                target.write(text)
                target.flush()
        for line in text.splitlines():
            normalized_line = line.rstrip("\r")
            self._tail.append(normalized_line)
            if normalized_line:
                self._summary_candidates.append(normalized_line)
            failure_match = self._COVERAGE_FAILURE_PATTERN.search(line)
            if failure_match:
                threshold_value = float(failure_match.group("threshold"))
                percent_value = float(failure_match.group("percent"))
                self._coverage_failure = (percent_value, threshold_value)
            for pattern in self._COVERAGE_PATTERNS:
                match = pattern.search(line)
                if match:
                    self._coverage_percent = float(match.group("percent"))
                    break

    def snapshot(self) -> PytestRun:
        """ساخت نمونهٔ نتایج محدود شده."""

        return PytestRun(
            returncode=0,
            stdout=self._stdout_buffer.getvalue(),
            stderr=self._stderr_buffer.getvalue(),
            tail_lines=tuple(self._tail),
            summary_candidates=tuple(self._summary_candidates),
            coverage_failure=self._coverage_failure,
            text_coverage_percent=self._coverage_percent,
        )



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


def _resolve_threshold(raw_primary: str | None, raw_alias: str | None) -> tuple[float, list[str]]:
    """محاسبهٔ آستانهٔ پوشش و پیام‌های هشدار مرتبط."""

    warnings: list[str] = []
    raw_value = raw_primary if raw_primary is not None else raw_alias
    if raw_value is None:
        return DEFAULT_THRESHOLD, warnings
    text = _normalize_threshold_text(str(raw_value).strip())
    normalized = text.casefold()
    if not text or normalized in {"null", "none", ""}:
        return DEFAULT_THRESHOLD, warnings
    if normalized == "0":
        return 0.0, warnings
    try:
        value = float(text)
    except ValueError:
        warnings.append("COV_THRESHOLD_DEFAULT: مقدار آستانه نامعتبر بود و مقدار 95 اعمال شد.")
        return DEFAULT_THRESHOLD, warnings
    if value < 0:
        warnings.append(
            "COV_INVALID_INPUT_CLAMPED: مقدار آستانه کمتر از صفر بود و به 95٪ بازنشانی شد."
        )
        return DEFAULT_THRESHOLD, warnings
    if value > 100:
        warnings.append(
            "COV_INVALID_INPUT_CLAMPED: مقدار آستانه بیش از 100٪ بود و به 100٪ محدود شد."
        )
        return 100.0, warnings
    return value, warnings


def _resolve_tail_limit(raw_value: str | None) -> int:
    """تعیین تعداد خطوط دنباله برای خروجی."""

    if not raw_value:
        return 200
    try:
        value = int(_normalize_threshold_text(raw_value))
    except ValueError:
        return 200
    return max(1, value)


def _resolve_capture_limit(raw_value: str | None) -> int:
    """تعیین سقف کاراکتر ذخیره‌شده در بافر."""

    if not raw_value:
        return DEFAULT_CAPTURE_CHAR_LIMIT
    try:
        value = int(_normalize_threshold_text(raw_value))
    except ValueError:
        return DEFAULT_CAPTURE_CHAR_LIMIT
    return max(10_000, value)


def _discover_tests() -> list[str]:
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
        f"{SUMMARY_PREFIX_FAILURE} PYTEST_COV_MISSING: لطفاً بسته pytest-cov را نصب کنید.\n"
    )


def _ensure_pytest_cov() -> None:
    """بررسی در دسترس بودن افزونه pytest-cov با مدیریت خطا."""

    from src.tools.cov_plugin_shim import PluginValidationError

    try:
        import pytest  # type: ignore
        from _pytest.config import get_config  # type: ignore
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


def _build_pytest_command(
    test_targets: Sequence[str],
    extra_args: Iterable[str],
    threshold: float,
) -> list[str]:
    """ساخت فرمان pytest برای اجرای پوشش."""

    command: list[str] = [
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
    return command


def _stream_pytest(
    command: Sequence[str],
    *,
    summary_mode: bool,
    tail_limit: int,
    capture_char_limit: int,
) -> PytestRun:
    """اجرای pytest با برش جریان خروجی برای کنترل حافظه."""

    env = os.environ.copy()
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("COVERAGE_GATE_STREAM_ERROR|جریان استاندارد در دسترس نیست")
    collector = StreamCollector(
        tail_limit=tail_limit,
        capture_char_limit=capture_char_limit,
        echo_stdout=not summary_mode,
        echo_stderr=not summary_mode,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while selector.get_map():
            for key, _ in selector.select(timeout=0.1):
                stream_name = key.data
                stream = key.fileobj
                line = stream.readline()
                if line:
                    collector.consume(line, stream_name)
                else:
                    selector.unregister(stream)
            if process.poll() is not None and not selector.get_map():
                break
        remaining_stdout = process.stdout.read()
        if remaining_stdout:
            collector.consume(remaining_stdout, "stdout")
        remaining_stderr = process.stderr.read()
        if remaining_stderr:
            collector.consume(remaining_stderr, "stderr")
    finally:
        selector.close()
    returncode = process.wait()
    snapshot = collector.snapshot()
    return PytestRun(
        returncode=returncode,
        stdout=snapshot.stdout,
        stderr=snapshot.stderr,
        tail_lines=snapshot.tail_lines,
        summary_candidates=snapshot.summary_candidates,
        coverage_failure=snapshot.coverage_failure,
        text_coverage_percent=snapshot.text_coverage_percent,
    )


def _parse_coverage_xml() -> float | None:
    """خواندن فایل coverage.xml در صورت وجود."""

    if not COVERAGE_XML.exists():
        return None
    try:
        tree = _safe_parse(COVERAGE_XML)
    except Exception as exc:  # pragma: no cover - defusedxml خطا می‌دهد
        sys.stderr.write(
            "COV_XML_INVALID: خواندن coverage.xml با خطا مواجه شد؛ از خروجی متنی استفاده می‌شود.\n"
        )
        sys.stderr.write(f"COV_XML_DETAIL: {exc}\n")
        return None
    root = tree.getroot()
    line_rate = root.get("line-rate") or "0"
    try:
        return float(line_rate) * 100
    except ValueError:
        sys.stderr.write(
            "COV_XML_INVALID: مقدار line-rate نامعتبر است؛ از خروجی متنی استفاده می‌شود.\n"
        )
        return None


def _resolve_coverage_percent(pytest_run: PytestRun) -> float:
    """تعیین درصد پوشش بر اساس XML یا خروجی متنی."""

    xml_percent = _parse_coverage_xml()
    if xml_percent is not None:
        return xml_percent
    if pytest_run.text_coverage_percent is not None:
        return pytest_run.text_coverage_percent
    sys.stderr.write(
        "COV_PERCENT_UNAVAILABLE: درصد پوشش در coverage.xml یا خروجی pytest یافت نشد.\n"
    )
    raise SystemExit(7)


def _threshold_passed(result: CoverageResult) -> bool:
    """ارزیابی عبور پوشش از آستانه."""

    return result.percent + 1e-9 >= result.threshold


def _summarize_pytest_output(lines: Sequence[str]) -> str:
    """استخراج یک خط خلاصه از خروجی pytest."""

    for line in reversed(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in ("passed", "failed", "error", "skipped")):
            return line
    return "هیچ خلاصه‌ای از pytest یافت نشد"


def _ensure_html_report() -> None:
    """اطمینان از وجود گزارش HTML برای بارگذاری در CI."""

    html_dir = PROJECT_ROOT / "htmlcov"
    if not html_dir.exists():
        sys.stderr.write(
            "COV_HTML_MISSING: دایرکتوری گزارش htmlcov تولید نشد؛ گزینه --cov-report=html را بررسی کنید.\n"
        )


def _format_percent(value: float) -> str:
    """نرمال‌سازی نمایش درصد برای خروجی فارسی."""

    formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _render_tail(pytest_run: PytestRun) -> str:
    """بازگردانی متن دنباله برای نمایش خطای خلاصه."""

    return "\n".join(pytest_run.tail_lines)


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
    threshold, warnings = _resolve_threshold(
        os.environ.get("COV_MIN"), os.environ.get("COV_MIN_PERCENT")
    )
    tail_limit = _resolve_tail_limit(os.environ.get(TAIL_LINE_LIMIT_ENV))
    capture_char_limit = _resolve_capture_limit(os.environ.get(CAPTURE_CHAR_LIMIT_ENV))
    extra_args = shlex.split(args.pytest_args)
    summary_mode = bool(args.summary)
    if args.targets:
        test_targets = args.targets
    else:
        test_targets = _discover_tests()
    for warning in warnings:
        sys.stdout.write(warning + "\n")
    _ensure_pytest_cov()
    command = _build_pytest_command(test_targets, extra_args, threshold)
    pytest_run = _stream_pytest(
        command,
        summary_mode=summary_mode,
        tail_limit=tail_limit,
        capture_char_limit=capture_char_limit,
    )
    if pytest_run.returncode == 5:
        sys.stderr.write(
            "COV_NO_TESTS: هیچ تست legacy مطابق الگو یافت نشد.\n"
        )
        sys.stdout.write(
            f"{SUMMARY_PREFIX_FAILURE} PYTEST_FAILED: اجرای pytest بدون تست منطبق پایان یافت.\n"
        )
        raise SystemExit(5)

    if pytest_run.returncode != 0:
        if pytest_run.coverage_failure is not None:
            percent_from_text, _ = pytest_run.coverage_failure
            try:
                percent_value = _resolve_coverage_percent(pytest_run)
            except SystemExit:
                percent_value = percent_from_text
            summary = (
                f"{SUMMARY_PREFIX_FAILURE} COV_BELOW_THRESHOLD: پوشش {_format_percent(percent_value)}٪ < آستانه"
                f" {_format_percent(threshold)}٪"
            )
            if not summary_mode:
                tail_output = _render_tail(pytest_run)
                if tail_output:
                    tail_count = len(pytest_run.tail_lines)
                    sys.stdout.write(
                        f"PYTEST_TAIL: آخرین {tail_count} خط خروجی pytest\n{tail_output}\n"
                    )
            sys.stdout.write(summary + "\n")
            _ensure_html_report()
            raise SystemExit(1)
        if not summary_mode:
            tail_output = _render_tail(pytest_run)
            if tail_output:
                tail_count = len(pytest_run.tail_lines)
                sys.stdout.write(
                    f"PYTEST_TAIL: آخرین {tail_count} خط خروجی pytest\n{tail_output}\n"
                )
        sys.stdout.write(
            f"{SUMMARY_PREFIX_FAILURE} PYTEST_FAILED: اجرای pytest با کد {pytest_run.returncode} متوقف شد.\n"
        )
        raise SystemExit(pytest_run.returncode)

    if not summary_mode:
        summary_line = _summarize_pytest_output(pytest_run.summary_candidates)
        sys.stdout.write(f"COV_PYTEST_SUMMARY: {summary_line}\n")

    percent = _resolve_coverage_percent(pytest_run)
    result = CoverageResult(percent=percent, threshold=threshold)
    summary = (
        f"{SUMMARY_PREFIX_SUCCESS} پوشش تست‌ها عبور کرد: {_format_percent(result.percent)}٪ ≥ آستانه"
        f" {_format_percent(result.threshold)}٪"
    )
    if not _threshold_passed(result):
        summary = (
            f"{SUMMARY_PREFIX_FAILURE} COV_BELOW_THRESHOLD: پوشش {_format_percent(result.percent)}٪ < آستانه"
            f" {_format_percent(result.threshold)}٪"
        )
        if not summary_mode:
            tail_output = _render_tail(pytest_run)
            if tail_output:
                tail_count = len(pytest_run.tail_lines)
                sys.stdout.write(
                    f"PYTEST_TAIL: آخرین {tail_count} خط خروجی pytest\n{tail_output}\n"
                )
        sys.stdout.write(summary + "\n")
        _ensure_html_report()
        raise SystemExit(1)

    sys.stdout.write(summary + "\n")
    _ensure_html_report()


if __name__ == "__main__":
    main()
