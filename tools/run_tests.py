"""ابزار اجرای تست‌ها با درنظر گرفتن گیت‌های CI و شرایط محلی."""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTEST_BIN = [sys.executable, "-m", "pytest"]
DEFAULT_COVERAGE_MIN = 80

HAS_PYTEST_COV = importlib.util.find_spec("pytest_cov") is not None
HAS_HYPOTHESIS = importlib.util.find_spec("hypothesis") is not None


class RunnerError(RuntimeError):
    """خطای سطح بالا برای مدیریت شکست اجراهای pytest."""


def _stable_env() -> dict[str, str]:
    """Create a deterministic environment for pytest runs."""

    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _parse_threshold(raw_value: str | None) -> str:
    """Return a safe coverage threshold derived from ``COVERAGE_MIN``.

    Args:
        raw_value: مقدار ورودی از متغیر محیطی ``COVERAGE_MIN``.

    Returns:
        مقدار متنی مناسب برای استفاده در گزینهٔ ``--cov-fail-under``.
    """

    if raw_value is None:
        return str(DEFAULT_COVERAGE_MIN)
    stripped = raw_value.strip()
    if not stripped:
        return str(DEFAULT_COVERAGE_MIN)
    try:
        numeric = float(stripped)
    except ValueError:
        print("⚠️ مقدار COVERAGE_MIN نامعتبر بود؛ مقدار پیش‌فرض 80 اعمال شد.")
        return str(DEFAULT_COVERAGE_MIN)
    if numeric < 0:
        print("⚠️ مقدار COVERAGE_MIN منفی بود؛ مقدار پیش‌فرض 80 اعمال شد.")
        return str(DEFAULT_COVERAGE_MIN)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def _run_pytest(args: Sequence[str], label: str) -> float:
    """Execute pytest with the requested arguments and return duration in ms."""

    command = [*PYTEST_BIN, *args]
    start = time.perf_counter()
    result = subprocess.run(command, cwd=str(ROOT), env=_stable_env(), check=False)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if result.returncode != 0:
        raise RunnerError(f"اجرای {label} با کد {result.returncode} شکست خورد.")
    print(f"✅ اجرای {label} با موفقیت پایان یافت.")
    return elapsed_ms


def _core_suite() -> float:
    """Run the curated core suite with coverage when امکان‌پذیر است."""

    target = "tests/ci_core"
    if HAS_PYTEST_COV:
        threshold = _parse_threshold(os.environ.get("COVERAGE_MIN"))
        args = [
            "-p",
            "pytest_cov",
            "--cov=sma",
            "--cov-report=xml",
            f"--cov-fail-under={threshold}",
            target,
        ]
    else:
        print(
            "⚠️ افزونه pytest-cov یافت نشد؛ اجرای محلی بدون سنجش پوشش انجام شد."
        )
        args = [target]
    return _run_pytest(args, "آزمایش‌های هسته")


def _golden_suite() -> float:
    """Execute the golden regression tests."""

    args = ["-m", "golden", "tests/test_exporter_golden.py"]
    return _run_pytest(args, "آزمایش‌های طلایی")


def _smoke_suite() -> float:
    """Run smoke و e2e با درنظر گرفتن نبود Hypothesis در محیط محلی."""

    args = ["-m", "smoke and e2e", "-q"]
    if not HAS_HYPOTHESIS:
        print(
            "⚠️ کتابخانه hypothesis نصب نیست؛ موارد دارای شناسه hypothesis_required کنار گذاشته شدند."
        )
        args.extend(["-k", "not hypothesis_required"])
    args.append("tests/test_smoke_e2e.py")
    return _run_pytest(args, "آزمایش‌های دود و انتهابه‌انتها")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and orchestrate the requested scopes."""

    parser = argparse.ArgumentParser(description="اجرای کنترل‌شدهٔ تست‌ها")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--core", action="store_true", help="اجرای تست‌های هسته")
    group.add_argument("--golden", action="store_true", help="اجرای تست‌های طلایی")
    group.add_argument("--smoke", action="store_true", help="اجرای تست‌های دود و e2e")
    group.add_argument("--all", action="store_true", help="اجرای تمام گیت‌ها")
    args = parser.parse_args(list(argv) if argv is not None else None)

    durations: list[float] = []
    try:
        if args.core:
            durations.append(_core_suite())
        elif args.golden:
            durations.append(_golden_suite())
        elif args.smoke:
            durations.append(_smoke_suite())
        elif args.all:
            durations.append(_core_suite())
            durations.append(_golden_suite())
            durations.append(_smoke_suite())
    except RunnerError as exc:
        print(f"❌ {exc}")
        return 1

    if os.environ.get("RUN_P95_CHECK") == "1" and durations:
        limit_raw = os.environ.get("P95_MS_ALLOCATIONS", "200")
        try:
            limit = int(limit_raw)
        except ValueError:
            print(
                "⚠️ مقدار P95_MS_ALLOCATIONS نامعتبر بود؛ مقدار پیش‌فرض 200 میلی‌ثانیه استفاده شد."
            )
            limit = 200
        sorted_samples = sorted(durations)
        index = max(int(len(sorted_samples) * 0.95) - 1, 0)
        measured = sorted_samples[index]
        if measured > limit:
            print(
                "❌ مقدار p95 اندازه‌گیری‌شده از حد مجاز عبور کرد و گیت کارایی شکست خورد."
            )
            return 1
        print(
            f"✅ مقدار p95 برابر {measured:.1f} میلی‌ثانیه و کمتر از حد {limit} بود."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
