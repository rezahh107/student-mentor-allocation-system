"""تهیهٔ فایل‌های CI با رعایت نسخهٔ vC+ و پیام‌های فارسی."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_DEV_PATH = ROOT / "requirements-dev.txt"
README_PATH = ROOT / "README_CI.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_MINIMUMS = {
    "pytest": "pytest>=7.4",
    "pytest-cov": "pytest-cov>=4.1",
    "hypothesis": "hypothesis>=6.100",
}

README_BODY = """# راهنمای اجرای پایپ‌لاین CI

این مخزن برای اطمینان از یکسان بودن نتایج در CI و اجراهای محلی سخت‌گیر شده است. برای آماده‌سازی وابستگی‌ها از دستور واحد زیر استفاده کنید تا وابستگی‌های اصلی و توسعه به‌طور همزمان نصب شوند:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

## اجرای محلی

اسکریپت `tools/run_tests.py` سه گیت اصلی را مشابه CI اجرا می‌کند اما در صورت نبود افزونه‌های اختیاری (مانند `pytest-cov` یا `hypothesis`) با پیام فارسی و حالت جایگزین ادامه می‌دهد:

```bash
python tools/run_tests.py --core
python tools/run_tests.py --golden
python tools/run_tests.py --smoke
```

گزینهٔ `--all` هر سه گیت را پشت سر هم اجرا می‌کند. برای اندازه‌گیری اختیاری p95، متغیرهای محیطی `RUN_P95_CHECK=1` و در صورت نیاز `P95_MS_ALLOCATIONS` را تنظیم کنید.

## اجرای CI

Workflow موجود در `.github/workflows/ci.yml` همان گیت‌ها را با سخت‌گیری کامل اجرا می‌کند:

- پوشش خطی با حداقل تعیین‌شده توسط `COVERAGE_MIN` (یا مقدار پیش‌فرض ۸۰) بررسی می‌شود.
- آزمون‌های طلایی با مقایسهٔ بایت‌به‌بایت اجرا می‌گردند.
- روی شاخهٔ `main` تنها مسیرهای دود و انتهابه‌انتها با دستور `pytest -m "smoke and e2e" -q` اجرا می‌شوند.

تمام پیام‌های خطا و خروجی‌ها به‌صورت فارسی و قطعی هستند تا تجربهٔ توسعه‌دهندگان یکسان بماند.
"""

WORKFLOW_BODY = """name: Hardened CI

on:
  workflow_dispatch:
  schedule:
    - cron: '0 3 * * *'
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths:
      - 'src/**'
      - 'tests/**'
      - 'application/**'
      - 'tools/**'
      - '.github/workflows/**'
      - 'requirements*.txt'
  push:
    branches:
      - main
    paths:
      - 'src/**'
      - 'tests/**'
      - 'application/**'
      - 'tools/**'
      - '.github/workflows/**'
      - 'requirements*.txt'

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  pr-core:
    # alias قبلی: ci
    # Spec compliance: PR gates اجراهای core+golden+coverage را تضمین می‌کند.
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    env:
      PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'
      LC_ALL: C.UTF-8
      PYTHONUTF8: '1'
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements*.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      - name: Install dependencies
        run: |
          python -m pip install -U pip
          pip install -r requirements.txt -r requirements-dev.txt
      - name: Core suite with coverage gate
        env:
          COVERAGE_MIN: ${{ vars.COVERAGE_MIN }}
        run: |
          pytest -p pytest_cov --cov=src --cov-report=xml --cov-fail-under=${{ env.COVERAGE_MIN || 80 }}
      - name: Golden determinism
        run: |
          pytest -m golden tests/test_exporter_golden.py
      - name: Upload coverage and reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: ci-artifacts
          if-no-files-found: ignore
          path: |
            coverage.xml
            tests/golden/**
            reports/**

  main-smoke:
    # alias قبلی: ci-smoke
    # Spec compliance: روی main فقط دود و e2e اجرا می‌شود.
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    env:
      PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'
      LC_ALL: C.UTF-8
      PYTHONUTF8: '1'
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements*.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      - name: Install dependencies
        run: |
          python -m pip install -U pip
          pip install -r requirements.txt -r requirements-dev.txt
      - name: Smoke and e2e suite
        run: |
          pytest -m "smoke and e2e" -q
"""


def _normalize_requirement(line: str) -> str:
    """Return the package identifier for comparison with required minimums."""

    token = line.strip().split()
    if not token:
        return ""
    candidate = token[0]
    for index, char in enumerate(candidate):
        if char in "<>=!":
            return candidate[:index].lower()
    return candidate.lower()


def _merge_requirements(existing: Iterable[str]) -> list[str]:
    """Combine existing requirements with enforced minimum versions."""

    seen: set[str] = set()
    merged: list[str] = []
    for raw in existing:
        cleaned = raw.strip()
        if not cleaned:
            continue
        key = _normalize_requirement(cleaned)
        if key in REQUIRED_MINIMUMS:
            if key not in seen:
                merged.append(REQUIRED_MINIMUMS[key])
                seen.add(key)
        else:
            merged.append(cleaned)
    for key, spec in REQUIRED_MINIMUMS.items():
        if key not in seen:
            merged.append(spec)
            seen.add(key)
    return merged


def _write_with_backup(path: Path, content: str) -> bool:
    """Write content to path creating a .bak backup when changes occur."""

    normalized = content.rstrip("\n") + "\n"
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == normalized:
            print(f"ℹ️  هیچ تغییری برای {path.name} لازم نبود.")
            return False
        backup = path.with_name(f"{path.name}.bak")
        backup.write_text(current, encoding="utf-8")
        print(f"💾 نسخهٔ پشتیبان در {backup.name} ذخیره شد.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")
    print(f"✅ فایل {path.name} با موفقیت نوشته شد.")
    return True


def ensure_requirements() -> None:
    """Ensure that requirements-dev.txt contains enforced minimums."""

    existing: list[str] = []
    if REQUIREMENTS_DEV_PATH.exists():
        existing = REQUIREMENTS_DEV_PATH.read_text(encoding="utf-8").splitlines()
    merged = _merge_requirements(existing)
    if _write_with_backup(REQUIREMENTS_DEV_PATH, "\n".join(merged)):
        print("✅ وابستگی‌های توسعه به‌روزرسانی شدند.")
    else:
        print("ℹ️  وابستگی‌های توسعه پیش‌تر منطبق بودند.")


def ensure_readme() -> None:
    """Write the CI guide in Persian with deterministic content."""

    _write_with_backup(README_PATH, README_BODY)


def ensure_workflow() -> None:
    """Write the hardened GitHub Actions workflow."""

    _write_with_backup(WORKFLOW_PATH, WORKFLOW_BODY)


def main(argv: list[str] | None = None) -> int:
    """Entry point for updating CI assets."""

    parser = argparse.ArgumentParser(description="به‌روزرسانی فایل‌های CI")
    parser.add_argument(
        "--only",
        choices=("requirements", "readme", "workflow"),
        help="در صورت نیاز فقط یک بخش را بازنویسی کنید.",
    )
    args = parser.parse_args(argv)
    target = args.only

    if target in (None, "requirements"):
        ensure_requirements()
    if target in (None, "readme"):
        ensure_readme()
    if target in (None, "workflow"):
        ensure_workflow()
    print("🎯 پیکربندی CI به پایان رسید.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
