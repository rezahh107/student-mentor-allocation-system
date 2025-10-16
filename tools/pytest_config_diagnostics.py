"""Pytest Configuration Fixer for GitHub Actions.

Diagnoses and fixes pytest invocation issues for cross-platform CI runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence
from datetime import datetime
import shutil

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
logger = logging.getLogger(__name__)


@dataclass
class OverrideIssue:
    kind: str
    message: str
    suggestion: str


class PytestConfigFixer:
    """Safe pytest configuration manager with backup and validation."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.backup_dir = self.project_root / ".config_backups"
        self.backup_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Backup helpers
    # ------------------------------------------------------------------
    def backup_file(self, path: Path) -> Optional[Path]:
        """Create a timestamped copy of *path* inside the backup directory."""
        if not path.exists():
            logger.debug("No backup created for %s; file missing", path)
            return None

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.backup_dir / f"{path.name}.{timestamp}.bak"
        shutil.copy2(path, backup_path)
        logger.info("Backup created at %s", backup_path)
        return backup_path

    # ------------------------------------------------------------------
    # Dependency validation
    # ------------------------------------------------------------------
    def validate_pytest_installation(self) -> dict:
        """Validate pytest and key plugins without using shell=True."""
        info: dict = {
            "python": sys.version,
            "pytest": None,
            "plugins": {},
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            info["pytest"] = result.stdout.strip()
            logger.info("Detected %s", info["pytest"])
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.error("pytest is not available: %s", exc)
            info["pytest"] = "missing"

        for plugin in ("pytest-xdist", "pytest-timeout"):
            info["plugins"][plugin] = self._probe_plugin(plugin)

        return info

    def _probe_plugin(self, name: str) -> Optional[str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", name],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Plugin %s is not installed", name)
            return None

        metadata: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()
        version = metadata.get("version")
        logger.info("Plugin %s version %s", name, version or "unknown")
        return version

    # ------------------------------------------------------------------
    # Error detection
    # ------------------------------------------------------------------
    _SMART_QUOTES = {
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
    }

    _OVERRIDE_PATTERN = re.compile(r"--override-ini(?:=|\s+)([^\s]+)")

    def detect_override_ini_issue(self, text: str) -> List[OverrideIssue]:
        """Inspect text (command or stderr) for override-ini typos."""
        issues: List[OverrideIssue] = []
        if "--override-ini" not in text:
            return issues

        normalized = text
        for bad, good in self._SMART_QUOTES.items():
            if bad in normalized:
                normalized = normalized.replace(bad, good)
                issues.append(
                    OverrideIssue(
                        kind="smart-quotes",
                        message=f"Non-ASCII quote detected: {bad}",
                        suggestion=f"Replace {bad} with {good}",
                    )
                )
        normalized = normalized.replace("'--override-ini', 'addopts=", "--override-ini addopts=")
        normalized = normalized.replace('"--override-ini", "addopts=', "--override-ini addopts=")

        matches = list(self._OVERRIDE_PATTERN.finditer(normalized))
        if not matches:
            issues.append(
                OverrideIssue(
                    kind="missing-override",
                    message="--override-ini option is malformed",
                    suggestion="Use --override-ini addopts=...",
                )
            )
            return issues

        for match in matches:
            option = match.group(1)
            if option.lower().startswith("adoptopts"):
                issues.append(
                    OverrideIssue(
                        kind="typo",
                        message="Option name 'adoptopts' is invalid",
                        suggestion="Use 'addopts' in --override-ini addopts=…",
                    )
                )
            if "=" not in option:
                issues.append(
                    OverrideIssue(
                        kind="missing-equals",
                        message="--override-ini should be provided as key=value",
                        suggestion="Format the flag as --override-ini addopts=",
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # pytest.ini helpers
    # ------------------------------------------------------------------
    @property
    def expected_pytest_ini(self) -> str:
        return (
            "# Managed by tools/pytest_config_diagnostics.py\n"
            "# Ensures deterministic CI behaviour across platforms.\n"
            "[pytest]\n"
            "minversion = 7.4\n"
            "pythonpath =\n"
            "    src\n"
            "testpaths =\n"
            "    tests/spec\n"
            "    tests/windows\n"
            "    tests/integration\n"
            "python_files = test_*.py *_test.py\n"
            "python_classes = Test* *Tests\n"
            "python_functions = test_*\n"
            "addopts =\n"
            "    -ra\n"
            "    --strict-config\n"
            "    --strict-markers\n"
            "    --color=yes\n"
            "    --maxfail=1\n"
            "    --durations=20\n"
            "    --tb=short\n"
            "    --showlocals\n"
            "    -W error\n"
            "    -n=auto\n"
            "    --dist=loadscope\n"
            "    -p pytest_asyncio\n"
            "    -p xdist.plugin\n"
            "    -p pytest_timeout\n"
            "xfail_strict = true\n"
            "console_output_style = progress\n"
            "filterwarnings =\n"
            "    error\n"
            "markers =\n"
            "    smoke: آزمون‌های دود\n"
            "    integration: آزمایش‌های یکپارچه‌سازی\n"
            "    windows: آزمون‌های مختص ویندوز\n"
            "    excel: آزمون‌های خروجی اکسل\n"
            "    excel_safety: آزمون‌های ایمنی اکسل و جلوگیری از تزریق فرمول\n"
            "    ci: آزمون‌های CI\n"
            "    retry_logic: آزمون منطق تلاش مجدد\n"
            "    middleware: آزمون زنجیره میان‌افزار RateLimit→Idempotency→Auth\n"
            "    performance: آزمون بودجه‌های کارایی\n"
            "    stress: آزمون‌های تنش (بار بالا)\n"
            "    ui: آزمون‌های رابط کاربری\n"
            "    metrics: آزمون‌های متریک و مشاهده‌پذیری\n"
            "    benchmark: آزمون‌های بنچمارک با pytest-benchmark\n"
            "    security: آزمون پایه‌های امنیتی\n"
            "    cleanup: آزمون پاکسازی حالت اشتراکی\n"
            "    network: آزمون‌های نیازمند شبکه (در صورت عدم دسترسی آفلاین حذف شوند)\n"
            "norecursedirs =\n"
            "    .git\n"
            "    .tox\n"
            "    .venv\n"
            "    venv\n"
            "    build\n"
            "    dist\n"
            "    node_modules\n"
            "    tmp\n"
            "    htmlcov\n"
            "    test-results\n"
            "env =\n"
            "    TZ=Asia/Tehran\n"
            "    PYTHONDONTWRITEBYTECODE=1\n"
            "    PYTHONUNBUFFERED=1\n"
            "    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\n"
            "    PYTHONHASHSEED=0\n"
            "    TEST_ENV=ci\n"
            "log_cli = true\n"
            "log_cli_level = INFO\n"
            "log_cli_format = %(asctime)s [%(levelname)s] %(name)s: %(message)s\n"
            "log_cli_date_format = %Y-%m-%dT%H:%M:%S%z\n"
            "junit_family = xunit2\n"
            "junit_logging = all\n"
            "junit_duration_report = call\n"
            "cache_dir = .pytest_cache\n"
            "timeout = 300\n"
            "timeout_func_only = false\n"
            "timeout_method = thread\n"
        )

    def ensure_pytest_ini(self, overwrite: bool = False) -> bool:
        """Ensure pytest.ini matches the expected baseline."""
        pytest_ini_path = self.project_root / "pytest.ini"
        desired = self.expected_pytest_ini
        if pytest_ini_path.exists():
            existing = pytest_ini_path.read_text(encoding="utf-8")
            if existing == desired:
                logger.info("pytest.ini already matches expected configuration")
                return True
            if not overwrite:
                logger.warning("pytest.ini differs from expected configuration")
                return False
            self.backup_file(pytest_ini_path)
        pytest_ini_path.write_text(desired, encoding="utf-8")
        logger.info("pytest.ini updated at %s", pytest_ini_path)
        return True

    # ------------------------------------------------------------------
    # Workflow inspection
    # ------------------------------------------------------------------
    def scan_workflow(self, workflow_path: Path) -> List[str]:
        """Extract pytest commands from a workflow file."""
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow not found: {workflow_path}")

        commands: List[str] = []
        with workflow_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                normalized = line.strip()
                if not normalized or normalized.startswith("#"):
                    continue
                if "pytest" in normalized:
                    commands.append(normalized)
        return commands

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------
    @staticmethod
    def recommended_command(tests: Sequence[str]) -> List[str]:
        base = [
            "python",
            "-m",
            "pytest",
            "--maxfail=1",
            "-n",
            "1",
            "-q",
            "--override-ini",
            "addopts=",
        ]
        return base + list(tests)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose pytest override-ini issues")
    parser.add_argument(
        "--error-text",
        help="Raw stderr or command string to analyse",
        default="",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        help="Optional workflow file to scan for problematic pytest invocations",
    )
    parser.add_argument(
        "--overwrite-pytest-ini",
        action="store_true",
        help="Update pytest.ini to the expected baseline after backing it up",
    )
    parser.add_argument(
        "--tests",
        nargs="*",
        help="Optional tests to include when printing the recommended command",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable output",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    args = parse_args(argv)
    fixer = PytestConfigFixer(project_root=Path.cwd())

    diagnostics: dict[str, object] = {
        "dependencies": fixer.validate_pytest_installation(),
        "issues": [],
        "workflow_commands": [],
        "recommended_command": None,
    }

    text_to_inspect = args.error_text or ""
    if args.workflow:
        commands = fixer.scan_workflow(args.workflow)
        diagnostics["workflow_commands"] = commands
        for command in commands:
            issues = fixer.detect_override_ini_issue(command)
            if issues:
                diagnostics["issues"].extend([issue.__dict__ for issue in issues])
        if commands:
            text_to_inspect += "\n" + "\n".join(commands)

    if text_to_inspect:
        issues = fixer.detect_override_ini_issue(text_to_inspect)
        diagnostics["issues"].extend([issue.__dict__ for issue in issues])

    if args.tests:
        diagnostics["recommended_command"] = fixer.recommended_command(args.tests)

    if args.overwrite_pytest_ini:
        fixer.ensure_pytest_ini(overwrite=True)

    if args.json:
        print(json.dumps(diagnostics, indent=2, ensure_ascii=False))
    else:
        logger.info("Diagnostics summary: %s", json.dumps(diagnostics, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
