"""Bandit-safe helpers for executing commands and parsing XML."""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

try:
    from defusedxml import ElementTree as _ElementTree
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    from xml.etree import ElementTree as _ElementTree  # nosec B314 - trusted local files only.

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
    )


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

