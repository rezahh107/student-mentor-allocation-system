"""Bootstrap utilities for Tailored v2.4."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from .fs_atomic import atomic_write_text
from .logging_utils import bilingual_message, configure_logging, correlation_id, log_event
from .retry import RetryError, retry

AGENT_FILES = (Path("AGENTS.md"), Path("agent.md"))
SCHEMA_DIR = Path(".ci") / "schemas"
PERSIAN_AGENT_ERROR = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
PERSIAN_PYTHON_ERROR = "نسخهٔ پایتون پشتیبانی نمی‌شود؛ لطفاً Python 3.11 یا جدیدتر نصب کنید."
PERSIAN_SCHEMA_ERROR = "طرح‌های JSON در مسیر .ci/schemas یافت نشد؛ فایل‌ها را بررسی کنید."
PERSIAN_CONSTRAINT_ERROR = "نصب باید بر اساس constraints-dev.txt انجام شود؛ لطفاً قفل وابستگی را به‌روز کنید."
PERSIAN_INSTALL_ERROR = "نصب وابستگی‌ها شکست خورد؛ ارتباط شبکه یا تنظیمات pip را بررسی کنید."

ENV_SNAPSHOT = Path("artifacts/shared/environment.json")
CONSTRAINTS_DEV = Path("constraints-dev.txt")
CONSTRAINTS_PROD = Path("constraints.txt")
REQUIREMENTS_DEV_IN = Path("requirements-dev.in")
REQUIREMENTS_IN = Path("requirements.in")


class BootstrapError(RuntimeError):
    """Raised when deterministic bootstrap prerequisites are not met."""


def _agent_path() -> Path:
    for candidate in AGENT_FILES:
        if candidate.is_file():
            return candidate
    raise BootstrapError(
        bilingual_message(
            PERSIAN_AGENT_ERROR,
            "AGENTS.md missing at repository root; add agents.md-compliant spec.",
        )
    )


def verify_agent_file() -> Path:
    path = _agent_path()
    log_event("agent_spec_detected", path=str(path))
    return path


def verify_python_version() -> None:
    if sys.version_info < (3, 11):
        raise BootstrapError(
            bilingual_message(
                PERSIAN_PYTHON_ERROR,
                "Unsupported Python version; install Python 3.11 or newer.",
            )
        )


def verify_schema_files() -> None:
    expected = (SCHEMA_DIR / "pytest.schema.json", SCHEMA_DIR / "strict_score.schema.json")
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise BootstrapError(
            bilingual_message(
                PERSIAN_SCHEMA_ERROR,
                f"Missing schema files: {', '.join(missing)}",
            )
        )


def verify_constraints() -> None:
    if not (CONSTRAINTS_DEV.is_file() and REQUIREMENTS_DEV_IN.is_file()):
        raise BootstrapError(
            bilingual_message(
                PERSIAN_CONSTRAINT_ERROR,
                "constraints-dev.txt or requirements-dev.in missing",
            )
        )
    if not (CONSTRAINTS_PROD.is_file() and REQUIREMENTS_IN.is_file()):
        raise BootstrapError(
            bilingual_message(
                PERSIAN_CONSTRAINT_ERROR,
                "constraints.txt or requirements.in missing",
            )
        )

    def _has_hashes(path: Path) -> bool:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return "--hash=" in content

    if not _has_hashes(CONSTRAINTS_DEV) or not _has_hashes(CONSTRAINTS_PROD):
        raise BootstrapError(
            bilingual_message(
                PERSIAN_CONSTRAINT_ERROR,
                "constraints files must include pip-tools --hash entries",
            )
        )


def _pip_install(arguments: Iterable[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", *arguments]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    attempts = int(env.get("CI_RETRY_ATTEMPTS", "3"))

    def runner() -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "pip install failed"
            raise RuntimeError(message)

    try:
        retry(runner, attempts=attempts, correlation_seed=correlation_id())
    except RetryError as exc:  # pragma: no cover - network heavy
        raise BootstrapError(bilingual_message(PERSIAN_INSTALL_ERROR, str(exc))) from exc


def install_dev_dependencies() -> None:
    verify_constraints()
    _pip_install(["-c", str(CONSTRAINTS_DEV), "-r", str(REQUIREMENTS_DEV_IN)])


def record_environment_snapshot(path: Path = ENV_SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "python": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "correlation_id": correlation_id(),
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def bootstrap() -> None:
    configure_logging()
    verify_agent_file()
    verify_python_version()
    verify_schema_files()
    install_dev_dependencies()
    record_environment_snapshot()
    log_event("bootstrap_complete")
