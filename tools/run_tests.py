"""Hardened pytest orchestrator with CI-compatible gates.

Spec compliance:
- PR گیت‌ها شامل core + golden + پوشش هستند.
- اجرای main فقط دود و e2e را فعال می‌کند.
- PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 در همهٔ اجراها تنظیم می‌شود.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Sequence
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PYTEST_COMMAND = [sys.executable, "-m", "pytest"]
DEFAULT_COVERAGE_MIN = 80.0
DEFAULT_P95_LIMIT_MS = 200.0
HAS_PYTEST_COV = importlib.util.find_spec("pytest_cov") is not None
HAS_PYTEST_ASYNCIO = importlib.util.find_spec("pytest_asyncio") is not None
HAS_HYPOTHESIS = importlib.util.find_spec("hypothesis") is not None
HAS_PYQT5 = importlib.util.find_spec("PyQt5") is not None
HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None
HAS_YAML = importlib.util.find_spec("yaml") is not None


class CommandError(RuntimeError):
    """Raised when a pytest invocation fails."""


def _truthy(value: str | None) -> bool:
    """Interpret environment variables with common falsy sentinels."""

    if value is None:
        return False
    lowered = value.strip().lower()
    return lowered not in {"", "0", "false", "no", "n"}


def _read_float_env(name: str, default: float) -> float:
    """Parse a float environment variable while handling invalid inputs."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        return default
    try:
        return float(stripped)
    except ValueError:
        print(f"⚠️ مقدار نامعتبر برای {name}: {raw!r}. مقدار پیش‌فرض استفاده شد.")
        return default


def _build_env() -> dict[str, str]:
    """Return a deterministic environment for pytest invocations."""

    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _run_pytest(args: Sequence[str], durations: List[float], description: str) -> None:
    """Execute pytest with *args* and record duration in milliseconds."""

    command = [*PYTEST_COMMAND, "-c", str(ROOT / "pytest.ini"), *args]
    start = time.perf_counter()
    result = subprocess.run(command, cwd=str(ROOT), env=_build_env(), check=False)
    elapsed = (time.perf_counter() - start) * 1000.0
    durations.append(elapsed)
    if result.returncode != 0:
        raise CommandError(f"اجرای {description} با کد {result.returncode} شکست خورد.")
    print(f"✅ اجرای {description} با موفقیت پایان یافت.")


def _enforce_coverage(minimum: float) -> None:
    """Validate that coverage.xml respects the configured minimum."""

    coverage_path = ROOT / "coverage.xml"
    if not coverage_path.exists():
        raise CommandError("گزارش پوشش coverage.xml پیدا نشد؛ گیت پوشش برقرار نماند.")
    try:
        tree = ET.parse(coverage_path)
    except ET.ParseError as exc:  # pragma: no cover - defensive
        raise CommandError(f"گزارش پوشش خوانا نیست: {exc}.") from exc
    root = tree.getroot()
    raw_rate = root.attrib.get("line-rate")
    if raw_rate is None:
        raise CommandError("گزارش پوشش خطی را اعلام نکرد؛ پیکربندی را بررسی کنید.")
    try:
        percentage = float(raw_rate) * 100.0
    except ValueError as exc:  # pragma: no cover - defensive
        raise CommandError(f"مقدار پوشش نامعتبر بود: {raw_rate!r}.") from exc
    if percentage + 1e-9 < minimum:
        raise CommandError(
            f"پوشش {percentage:.1f}% کمتر از حداقل {minimum:.1f}% است؛ گیت رد شد."
        )
    print(f"✅ پوشش {percentage:.1f}% حداقل {minimum:.1f}% را پاس کرد.")


def _should_check_p95() -> bool:
    """Return whether the optional p95 check is active."""

    return _truthy(os.environ.get("RUN_P95_CHECK"))


def _assert_p95_limit(durations: Sequence[float]) -> None:
    """Verify that the 95th percentile of durations stays within limits."""

    if not durations:
        print("ℹ️  برای بررسی p95 هیچ اندازه‌گیری‌ای ثبت نشد.")
        return
    limit = _read_float_env("P95_LIMIT_MS", DEFAULT_P95_LIMIT_MS)
    ordered = sorted(durations)
    index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    value = ordered[index]
    if value > limit:
        raise CommandError(
            f"p95 ثبت‌شده {value:.1f} میلی‌ثانیه است و از حد {limit:.1f} بیشتر شد."
        )
    print(f"✅ p95 برابر {value:.1f} میلی‌ثانیه و در محدوده است.")


def _core_args(ci_mode: bool) -> list[str]:
    """Return pytest arguments for the core test suite."""

    markers = ["not golden", "not smoke", "not e2e"]
    if HAS_PYTEST_ASYNCIO:
        args_preload = ["-p", "pytest_asyncio.plugin"]
    else:
        markers.append("not asyncio")
        args_preload = []
    args = ["-m", " and ".join(markers)]
    args.extend(args_preload)
    if HAS_PYTEST_COV and ci_mode:
        coverage_path = ROOT / "coverage.xml"
        if coverage_path.exists():
            coverage_path.unlink()
        args.extend(["-p", "pytest_cov"])
        args.extend([
            "--cov=src",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ])
    elif not HAS_PYTEST_COV:
        print(
            "⚠️ افزونه pytest-cov یافت نشد؛ اجرای محلی بدون پوشش انجام شد و برای CI الزامیه."
        )
    else:
        print("ℹ️  پوشش کد در اجراهای محلی بدون گیت CI محاسبه نشد.")
    return args


def _core_targets(ci_mode: bool) -> list[str]:
    """Select filesystem targets for the core suite respecting dependencies."""

    unit_path = ROOT / "tests" / "unit"
    all_tests = ROOT / "tests"
    targets = [str(unit_path)]
    missing_messages: list[str] = []
    if ci_mode:
        if not (HAS_PYQT5 and HAS_PYSIDE6 and HAS_YAML and HAS_HYPOTHESIS):
            raise CommandError("وابستگی‌های گرافیکی یا تحلیلی برای اجرای هسته در CI کامل نیست.")
        return [str(all_tests)]
    if not HAS_PYQT5 or not HAS_PYSIDE6:
        missing_messages.append(
            "کتابخانه‌های رابط کاربری نصب نشده‌اند؛ تست‌های یکپارچه‌سازی در اجراهای محلی رد شدند."
        )
    if not HAS_YAML:
        missing_messages.append("کتابخانه yaml نصب نیست؛ تست‌های مهاجرت داده در اجراهای محلی رد شدند.")
    if not HAS_HYPOTHESIS:
        missing_messages.append(
            "کتابخانه hypothesis نصب نیست؛ تست‌های نرمال‌سازی در اجراهای محلی رد شدند."
        )
    if not missing_messages:
        targets.append(str(all_tests))
    else:
        for message in missing_messages:
            print(f"⚠️ {message}")
    return targets


def _run_core(durations: List[float]) -> None:
    """Execute the core test suite and enforce coverage if possible."""

    ci_mode = _truthy(os.environ.get("CI"))
    if ci_mode and not HAS_PYTEST_COV:
        raise CommandError("افزونه pytest-cov باید در CI فعال باشد.")
    if ci_mode and not HAS_PYTEST_ASYNCIO:
        raise CommandError("افزونه pytest-asyncio در CI موجود نیست.")
    if not ci_mode and not HAS_PYTEST_ASYNCIO:
        print("⚠️ افزونه pytest-asyncio نصب نیست؛ تست‌های async در اجراهای محلی رد شدند.")
    args = [*_core_args(ci_mode), *_core_targets(ci_mode)]
    _run_pytest(args, durations, "هسته")
    if HAS_PYTEST_COV and ci_mode:
        minimum = _read_float_env("COVERAGE_MIN", DEFAULT_COVERAGE_MIN)
        _enforce_coverage(minimum)
    elif HAS_PYTEST_COV:
        print("ℹ️  گزارش پوشش فقط جهت اطلاع ایجاد شد؛ گیت در اجراهای محلی اعمال نشد.")
    else:
        print("ℹ️  گیت پوشش به‌دلیل نبود pytest-cov در اجراهای محلی رد نشد.")


def _run_golden(durations: List[float]) -> None:
    """Execute deterministic golden tests."""

    target = Path("tests") / "test_exporter_golden.py"
    _run_pytest(["-m", "golden", str(target)], durations, "طلایی")


def _run_smoke(durations: List[float]) -> None:
    """Execute smoke and end-to-end tests with graceful fallbacks."""

    if not HAS_HYPOTHESIS and not _truthy(os.environ.get("CI")):
        print("⚠️ کتابخانه hypothesis نصب نیست (محلی)؛ مسیر دود نادیده گرفته شد.")
        return
    _run_pytest(["-m", "smoke or e2e"], durations, "دود و e2e")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and orchestrate the requested test scope."""

    parser = argparse.ArgumentParser(description="اجرای کنترل‌شدهٔ تست‌ها")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--core", action="store_true", help="اجرای تست‌های هسته")
    scope.add_argument("--golden", action="store_true", help="اجرای تست‌های طلایی")
    scope.add_argument("--smoke", action="store_true", help="اجرای تست‌های دود/e2e")
    scope.add_argument("--all", action="store_true", help="اجرای تمام گیت‌ها")
    args = parser.parse_args(argv)

    durations: List[float] = []
    try:
        if args.core:
            _run_core(durations)
        elif args.golden:
            _run_golden(durations)
        elif args.smoke:
            _run_smoke(durations)
        elif args.all:
            _run_core(durations)
            _run_golden(durations)
            _run_smoke(durations)
    except CommandError as exc:
        print(f"❌ {exc}")
        return 1

    if _should_check_p95():
        try:
            _assert_p95_limit(durations)
        except CommandError as exc:
            print(f"❌ {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
