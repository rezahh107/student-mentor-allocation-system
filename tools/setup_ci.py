"""Configure hardened CI assets.

This module writes deterministic configuration files for the hardened CI
pipeline described in the engineering spec. All log messages are emitted in
Persian to align with local developer expectations.
"""
from __future__ import annotations

import argparse
import sys
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


def _normalize_requirement(line: str) -> str:
    """Return the package key for a requirement line.

    Parameters
    ----------
    line:
        Raw requirement specification.

    Returns
    -------
    str
        Normalized package key for matching against required minimums.
    """

    tokens = line.strip().split()
    if not tokens:
        return ""
    candidate = tokens[0]
    for index, char in enumerate(candidate):
        if char in "<>=!":
            return candidate[:index].lower()
    return candidate.lower()


def _merge_requirements(existing: Iterable[str]) -> list[str]:
    """Merge required minimum versions with existing requirement lines."""

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
    """Write *content* to *path* creating a ``.bak`` backup if needed."""

    encoded = content.rstrip("\n") + "\n"
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == encoded:
            print(f"ℹ️  هیچ تغییری برای {path.name} لازم نبود.")
            return False
        backup = path.with_name(f"{path.name}.bak")
        backup.write_text(current, encoding="utf-8")
        print(f"💾 نسخهٔ پشتیبان در {backup.name} ذخیره شد.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")
    print(f"✅ فایل {path.name} با موفقیت نوشته شد.")
    return True


def ensure_requirements() -> None:
    """Guarantee that ``requirements-dev.txt`` contains the hardened minimums."""

    existing: list[str] = []
    if REQUIREMENTS_DEV_PATH.exists():
        existing = REQUIREMENTS_DEV_PATH.read_text(encoding="utf-8").splitlines()
    merged = _merge_requirements(existing)
    content = "\n".join(merged)
    if _write_with_backup(REQUIREMENTS_DEV_PATH, content):
        print("✅ وابستگی‌های توسعه به‌روزرسانی شدند.")
    else:
        print("ℹ️  وابستگی‌های توسعه پیش‌تر منطبق بودند.")


def ensure_readme() -> None:
    """Ensure the Persian CI readme is available for contributors."""

    readme_body = (
        "# راهنمای اجرای پایپ‌لاین CI\n\n"
        "این مخزن برای اطمینان از یکسان بودن نتایج در CI و اجراهای محلی سخت‌گیر شده است."
        " برای آماده‌سازی وابستگی‌ها از دستورهای زیر استفاده کنید:\n\n"
        "```bash\n"
        "pip install -r requirements.txt -r requirements-dev.txt\n"
        "```\n\n"
        "پس از نصب وابستگی‌ها می‌توانید اسکریپت‌های درون `tools/` را اجرا کنید تا"
        " گیت‌های پوشش کد، آزمون‌های طلایی و دود را مشابه CI بررسی کنید.\n"
    )
    _write_with_backup(README_PATH, readme_body)


def ensure_workflow() -> None:
    """Write the hardened GitHub Actions workflow with deterministic content."""

    workflow = (
        "name: Hardened CI\n\n"
        "on:\n"
        "  pull_request:\n"
        "    types: [opened, synchronize, reopened, ready_for_review]\n"
        "  push:\n"
        "    branches:\n"
        "      - main\n\n"
        "jobs:\n"
        "  pr-core:\n"
        "    # alias قبلی: ci\n"
        "    # Spec compliance: PR gates اجراهای core+golden+coverage را تضمین می‌کند.\n"
        "    if: github.event_name == 'pull_request'\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Checkout repository\n"
        "        uses: actions/checkout@v4\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "      - name: Install dependencies\n"
        "        run: |\n"
        "          python -m pip install -U pip\n"
        "          pip install -r requirements.txt -r requirements-dev.txt\n"
        "      - name: Core suite with coverage gate\n"
        "        env:\n"
        "          PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'\n"
        "          COVERAGE_MIN: ${{ vars.COVERAGE_MIN }}\n"
        "        run: python tools/run_tests.py --core\n"
        "      - name: Golden determinism\n"
        "        env:\n"
        "          PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'\n"
        "        run: python tools/run_tests.py --golden\n\n"
        "  main-smoke:\n"
        "    # alias قبلی: ci-smoke\n"
        "    # Spec compliance: روی main فقط دود و e2e اجرا می‌شود.\n"
        "    if: github.event_name == 'push' && github.ref == 'refs/heads/main'\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Checkout repository\n"
        "        uses: actions/checkout@v4\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "      - name: Install dependencies\n"
        "        run: |\n"
        "          python -m pip install -U pip\n"
        "          pip install -r requirements.txt -r requirements-dev.txt\n"
        "      - name: Smoke and e2e suite\n"
        "        env:\n"
        "          PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1'\n"
        "        run: python tools/run_tests.py --smoke\n"
    )
    _write_with_backup(WORKFLOW_PATH, workflow)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CI bootstrapper."""

    parser = argparse.ArgumentParser(description="راه‌اندازی تنظیمات CI")
    parser.add_argument(
        "--only",
        choices=("requirements", "readme", "workflow"),
        help="در صورت نیاز فقط یکی از بخش‌ها را به‌روزرسانی کنید.",
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
    sys.exit(main())
