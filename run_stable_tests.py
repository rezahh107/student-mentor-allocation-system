#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def _safe_print(message: str = "") -> None:
    """Print text even when console encoding lacks emoji support."""

    encoding = sys.stdout.encoding or "utf-8"
    try:
        sys.stdout.write(f"{message}\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode(encoding, errors="ignore"))
    sys.stdout.flush()


class TestRunner:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.start_time = time.time()

    def run_command(self, cmd: list[str], name: str) -> bool:
        _safe_print(f"\n🧪 {name}...")
        _safe_print(f"📝 Command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True)
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.returncode == 0:
            if "SKIPPED" in stdout:
                _safe_print(f"⚠️  {name}: SKIPPED")
                self.skipped += 1
            else:
                _safe_print(f"✅ {name}: PASSED")
                self.passed += 1
            return True

        _safe_print(f"❌ {name}: FAILED")
        if stdout:
            _safe_print("📄 Stdout (tail):")
            _safe_print(stdout[-800:])
        if stderr:
            _safe_print("🚨 Stderr (tail):")
            _safe_print(stderr[-400:])
        self.failed += 1
        return False

    def run_test_suite(self, modules: list[str], name: str) -> bool:
        cmd = [sys.executable, "-m", "pytest", *modules, "-v", "--tb=short"]
        return self.run_command(cmd, name)

    def run_coverage(self, modules: list[str]) -> bool:
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--cov=sma",
            "--cov-report=term",
            "--cov-report=html",
            "--cov-fail-under=0",
            *modules,
        ]
        return self.run_command(cmd, "📊 Coverage Report")


def main() -> int:
    runner = TestRunner()

    _safe_print("🎯 Smart Allocation Test Suite")
    _safe_print("=" * 50)
    _safe_print("🖥️  Platform: Windows (Headless Optimized)")
    _safe_print(f"🐍 Python: {sys.version.split()[0]}")
    _safe_print(f"📂 Working Dir: {Path.cwd()}")

    _safe_print("\n" + "=" * 50)
    _safe_print("🔧 PHASE 1: Core Tests")
    _safe_print("=" * 50)

    core_success = True
    core_tests = [
        (["tests/unit/"], "Unit Tests"),
        (["tests/integration/"], "Integration Tests"),
        (["tests/performance/"], "Performance Tests"),
    ]
    for modules, name in core_tests:
        if not runner.run_test_suite(modules, name):
            core_success = False

    _safe_print("\n" + "=" * 50)
    _safe_print("📱 PHASE 2: UI Tests (Targeted)")
    _safe_print("=" * 50)

    ui_success = True
    ui_tests = [
        (["tests/ui/test_allocation_page.py"], "Allocation Page"),
        (["tests/ui/test_dashboard_page.py"], "Dashboard Page"),
    ]
    for modules, name in ui_tests:
        if not runner.run_test_suite(modules, name):
            ui_success = False

    if core_success and ui_success:
        _safe_print("\n" + "=" * 50)
        _safe_print("📊 PHASE 3: Coverage Analysis")
        _safe_print("=" * 50)
        coverage_modules = [
            "tests/unit/",
            "tests/integration/",
            "tests/ui/test_allocation_page.py",
            "tests/ui/test_dashboard_page.py",
        ]
        runner.run_coverage(coverage_modules)
    else:
        _safe_print("\n⚠️  Coverage skipped due to earlier failures")

    _safe_print("\n" + "=" * 60)
    _safe_print("📋 FINAL REPORT")
    _safe_print("=" * 60)

    elapsed = time.time() - runner.start_time
    _safe_print(f"⏱️  Total Time: {elapsed:.1f}s")
    _safe_print(f"✅ Passed: {runner.passed}")
    _safe_print(f"❌ Failed: {runner.failed}")
    _safe_print(f"⚠️  Skipped: {runner.skipped} (expected: PDF / Import / Realtime)")

    if runner.failed == 0:
        _safe_print("\n🎉 SUCCESS: All critical tests passed!")
        _safe_print("📊 Coverage report: htmlcov/index.html")
        _safe_print("🚀 Project ready for deployment")
        return 0

    _safe_print("\n🚨 ISSUES: Some test suites failed – see logs above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
