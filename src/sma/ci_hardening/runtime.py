"""Runtime guards ensuring deterministic cross-platform behaviour."""

from __future__ import annotations

import platform
import sys
from collections.abc import Iterable
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_SUPPORTED_MINOR = 11
_REQUIRED_MAJOR = 3
_REQUIRED_PATCH = 9
_MIN_UNSUPPORTED_MINOR = 13

_PATCH_MESSAGE = (
    "نسخهٔ پایتون پشتیبانی نمی‌شود؛ لطفاً دقیقاً Python 3.11.9 را فعال کنید."
)
_UNSUPPORTED_MINOR_MESSAGE = (
    "نسخهٔ پایتون پشتیبانی نمی‌شود؛ لطفاً Python 3.11 نصب/فعال کنید."
)
_UNSUPPORTED_MINOR_NEWER_MESSAGE = (
    "نسخهٔ پایتون پشتیبانی نمی‌شود؛ لطفاً Python 3.11 نصب/فعال کنید. "
    "بسته‌های وابسته برای این نسخه منتشر نشده‌اند."
)
_TZDATA_MESSAGE = (
    "منطقهٔ زمانی در دسترس نیست؛ بستهٔ tzdata را مطابق constraints نصب کنید."
)


class RuntimeConfigurationError(RuntimeError):
    """Raised when runtime prerequisites are not satisfied."""


_AGENTS_FILENAMES = ("AGENTS.md", "agent.md")
_AGENTS_MISSING_MESSAGE = (
    "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
)


def ensure_python_311() -> None:
    """Ensure the interpreter is Python 3.11.x.

    Raises:
        RuntimeConfigurationError: Raised when the interpreter version is unsupported.
    """

    version = sys.version_info
    if version.major != _REQUIRED_MAJOR or version.minor != _SUPPORTED_MINOR:
        message = _UNSUPPORTED_MINOR_MESSAGE
        if version.minor >= _MIN_UNSUPPORTED_MINOR:
            message = _UNSUPPORTED_MINOR_NEWER_MESSAGE
        raise RuntimeConfigurationError(message)
    if version.micro != _REQUIRED_PATCH:
        raise RuntimeConfigurationError(_PATCH_MESSAGE)


def is_uvloop_supported() -> bool:
    """Return ``True`` when ``uvloop`` may be safely enabled on this platform.

    Returns:
        ``True`` when the current platform supports ``uvloop``.
    """

    return platform.system().lower() not in {"windows"}


def ensure_tehran_tz() -> ZoneInfo:
    """Ensure the Asia/Tehran timezone is installed and usable.

    Returns:
        ``ZoneInfo`` instance for ``Asia/Tehran`` when available.

    Raises:
        RuntimeConfigurationError: If tzdata is missing and the timezone cannot
            be loaded.
    """

    try:
        return ZoneInfo("Asia/Tehran")
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - fatal path
        raise RuntimeConfigurationError(_TZDATA_MESSAGE) from exc


def _default_search_roots() -> list[Path]:
    """Return candidate directories to look for ``AGENTS.md``.

    Returns:
        List of directories to inspect for the manifest file.
    """

    roots: list[Path] = []
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if candidate not in roots:
            roots.append(candidate)
    return roots


def ensure_agents_manifest(roots: Iterable[Path] | None = None) -> Path:
    """Ensure an AGENTS manifest is available within the repository tree.

    Args:
        roots: Optional iterable of directories to search.

    Returns:
        Path to the discovered manifest file.

    Raises:
        RuntimeConfigurationError: If no manifest file is found.
    """

    search_roots = list(roots) if roots is not None else _default_search_roots()
    for root in search_roots:
        for filename in _AGENTS_FILENAMES:
            candidate = root / filename
            if candidate.is_file():
                return candidate
    raise RuntimeConfigurationError(_AGENTS_MISSING_MESSAGE)


__all__ = [
    "RuntimeConfigurationError",
    "ensure_agents_manifest",
    "ensure_python_311",
    "ensure_tehran_tz",
    "is_uvloop_supported",
]
