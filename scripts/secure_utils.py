"""Bandit-safe helpers for executing commands and parsing XML."""
from __future__ import annotations

import logging
import shlex
import subprocess  # استفاده کنترل‌شده از subprocess برای اجرای دستورات مجاز. # nosec B404
from pathlib import Path
from typing import Mapping, Sequence

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sma.core.logging_config import setup_logging

setup_logging()

try:
    from defusedxml import ElementTree as _ElementTree
except ModuleNotFoundError as error:  # pragma: no cover - defusedxml باید نصب باشد
    raise RuntimeError("کتابخانه defusedxml برای پردازش امن XML الزامی است.") from error

LOGGER = logging.getLogger(__name__)
_COMMAND_WHITELIST = {"git", "python", "make"}


def run_secure_command(
    command: Sequence[str] | str,
    *,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a whitelisted command securely."""

    if isinstance(command, str):
        parts = shlex.split(command)
    else:
        parts = list(command)
    if not parts:
        raise ValueError("دستور برای اجرا تعیین نشده است.")
    executable = parts[0]
    if executable not in _COMMAND_WHITELIST:
        raise ValueError("اجرای این دستور مجاز نیست.")
    LOGGER.debug("Running secure command", extra={"command": parts})
    safe_env = dict(env) if env is not None else None
    return subprocess.run(
        parts,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=safe_env,
    )  # ورودی‌ها پیش‌تر بازبینی شده‌اند و shell=False است. # nosec B603


def parse_secure_xml(path: str | Path) -> _ElementTree.ElementTree:
    """Parse XML content from a trusted local file path."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"فایل XML یافت نشد: {resolved}")
    if resolved.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("حجم فایل برای پردازش ایمن بسیار بزرگ است.")
    with resolved.open("rb") as handle:
        LOGGER.debug("Parsing XML file", extra={"path": str(resolved)})
        return _ElementTree.parse(handle)


__all__ = ["run_secure_command", "parse_secure_xml"]

