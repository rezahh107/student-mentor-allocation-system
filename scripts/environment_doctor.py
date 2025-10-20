import importlib
import os
import shutil
import subprocess  # اجرای کنترل‌شده دستورات کمکی. # nosec B404
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sma.core.logging_config import setup_logging

setup_logging()


REQUIRED_MODULES: List[str] = ["pytest", "streamlit", "pandas"]
MIN_PYTHON = (3, 8)


def _normalize_paths(entries: List[str]) -> List[str]:
    normalized: List[str] = []
    for raw in entries:
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            normalized.append(str(Path(candidate).resolve()))
        except (OSError, RuntimeError):
            normalized.append(candidate)
    return normalized


class EnvironmentDoctor:
    def __init__(self) -> None:
        self.issues: List[str] = []
        self.fixes: List[str] = []
        self.critical_issues: List[str] = []

    def diagnose(self) -> bool:
        """Run all diagnostic checks and return True when no critical issues exist."""
        print("🔍 Diagnosing environment...")

        self._check_python_version()
        self._check_pythonpath()
        self._check_dependencies()
        self._check_vscode_config()
        self._check_docker()

        return len(self.critical_issues) == 0

    def report(self) -> None:
        """Print a summary of findings and suggested fixes."""
        print("\n📋 Environment Diagnostic Report:")

        if self.issues:
            print("\n⚠️ Issues Found:")
            for issue in self.issues:
                print(f"  - {issue}")

        if self.critical_issues:
            print("\n❌ Critical Issues:")
            for issue in self.critical_issues:
                print(f"  - {issue}")

        if not self.issues and not self.critical_issues:
            print("✅ No issues detected! Environment is healthy.")

        if self.fixes:
            print("\n🔧 Recommended Fixes:")
            for index, fix in enumerate(self.fixes, 1):
                print(f"  {index}. {fix}")

    def auto_fix(self) -> bool:
        """Attempt to remediate non-critical issues automatically."""
        if not self.issues and not self.critical_issues:
            print("✅ No issues to fix!")
            return True

        print("\n🔧 Attempting to fix issues automatically...")

        project_root = str(Path.cwd().resolve())
        pythonpath = os.environ.get("PYTHONPATH")
        if not pythonpath:
            os.environ["PYTHONPATH"] = project_root
            print("✅ Set PYTHONPATH to current directory")
        else:
            segments = _normalize_paths(pythonpath.split(os.pathsep))
            if project_root not in segments:
                updated = pythonpath + os.pathsep + project_root
                os.environ["PYTHONPATH"] = updated
                print("✅ Added project root to PYTHONPATH")

        if any("Missing dependency" in issue for issue in self.issues):
            print("📦 Installing dependencies via hashed constraints...")
            ensure_lock_cmd = [
                sys.executable,
                "-m",
                "scripts.deps.ensure_lock",
                "--root",
                project_root,
                "install",
            ]
            try:
                subprocess.run(ensure_lock_cmd, check=True, capture_output=True)
                print("✅ constraints-dev.txt applied deterministically")
            except subprocess.CalledProcessError as exc:
                print("❌ نصب وابستگی‌ها بر اساس constraints-dev.txt با خطا روبه‌رو شد.")
                print(exc.stderr or exc.stdout)
                return False
            editable_cmd = [sys.executable, "-m", "pip", "install", "--no-deps", "-e", project_root]
            try:
                subprocess.run(editable_cmd, check=True, capture_output=True)
                print("✅ پروژه به صورت editable نصب شد")
            except subprocess.CalledProcessError as exc:
                print("❌ نصب editable با خطا روبه‌رو شد.")
                print(exc.stderr or exc.stdout)
                return False

        vscode_dir = Path(".vscode")
        if not vscode_dir.exists():
            vscode_dir.mkdir()
            print("✅ Created .vscode directory")

        return True

    def _check_python_version(self) -> None:
        current = sys.version_info[:2]
        if current < MIN_PYTHON:
            message = (
                f"Python version {current[0]}.{current[1]} is below minimum required {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
            )
            self.critical_issues.append(message)
            self.fixes.append(f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ from python.org")

    def _check_pythonpath(self) -> None:
        pythonpath = os.environ.get("PYTHONPATH")
        project_root = str(Path.cwd().resolve())
        if not pythonpath:
            self.issues.append("PYTHONPATH environment variable not set")
            self.fixes.append("Set PYTHONPATH to project root via setup.py, activate scripts, or .env")
            return

        segments = _normalize_paths(pythonpath.split(os.pathsep))
        if project_root not in segments:
            self.issues.append("PYTHONPATH does not include the project root")
            self.fixes.append("Add project root to PYTHONPATH or re-run python setup.py")

    def _check_dependencies(self) -> None:
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
            except ImportError:
                self.issues.append(f"Missing dependency: {module}")
                self.fixes.append(f"Install {module}: pip install {module}")

    def _check_vscode_config(self) -> None:
        vscode_dir = Path(".vscode")
        if not vscode_dir.exists():
            self.issues.append(".vscode directory missing")
            self.fixes.append("Create .vscode directory and add tasks.json")
            return

        tasks_file = vscode_dir / "tasks.json"
        if not tasks_file.exists():
            self.issues.append("tasks.json file missing")
            self.fixes.append("Create tasks.json file in .vscode directory")

    def _check_docker(self) -> None:
        docker_path = shutil.which("docker")
        if docker_path is None:
            self.issues.append("Docker not found in PATH")
            self.fixes.append("Install Docker from docker.com")
            return

        try:
            subprocess.run([docker_path, "--version"], check=True, capture_output=True)  # بررسی نسخه docker با ورودی ثابت. # nosec B603
        except subprocess.CalledProcessError:
            self.issues.append("Docker installation appears broken")
            self.fixes.append("Reinstall Docker from docker.com")


def check_pythonpath() -> bool:
    """Standalone helper to verify PYTHONPATH is pointing at the project root."""
    project_root = str(Path.cwd().resolve())
    pythonpath = os.environ.get("PYTHONPATH")
    if not pythonpath:
        print("❌ PYTHONPATH is not set.")
        print("🔧 Tip: run python setup.py or use activate scripts to configure it.")
        return False

    segments = _normalize_paths(pythonpath.split(os.pathsep))
    if project_root not in segments:
        print("❌ PYTHONPATH does not include the project root.")
        print("🔧 Tip: append the project root or re-run python setup.py.")
        return False

    print(f"✅ PYTHONPATH is configured correctly: {pythonpath}")
    return True


if __name__ == "__main__":
    doctor = EnvironmentDoctor()
    healthy = doctor.diagnose()
    doctor.report()

    if not healthy:
        try:
            fix = input("\nAttempt to automatically fix issues? (y/N): ").strip().lower() == "y"
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️ Auto-fix skipped by user input.")
            sys.exit(1)

        if fix:
            success = doctor.auto_fix()
            if success:
                print("\n🎉 Issues fixed successfully!")
            else:
                print("\n⚠️ Some issues could not be fixed automatically.")
