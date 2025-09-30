"""Compatibility shim for legacy tooling.

This repository now uses pyproject.toml with setuptools.build_meta. Any direct
invocation of setup.py should fail fast with a deterministic Persian message so
that CI systems remain non-interactive.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable

_ERROR_MESSAGE = (
    "اجرای setup.py پشتیبانی نمی‌شود؛ لطفاً از «pip install .[test]» یا "
    "«python -m build» بر پایهٔ pyproject.toml استفاده کنید."
)
_ALLOWED_AUTOMATION_COMMANDS: frozenset[str] = frozenset(
    {"egg_info", "build", "sdist", "bdist_wheel"}
)
_BANNED_COMMANDS: frozenset[str] = frozenset({"install", "develop"})


def _load_setup_callable():
    try:
        from setuptools import setup as setup_callable  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - defensive branch
        raise SystemExit(_ERROR_MESSAGE) from exc
    return setup_callable


def _is_automation_invocation(args: Iterable[str]) -> bool:
    if os.environ.get("PIP_BUILD_TRACKER"):
        return True
    return any(arg in _ALLOWED_AUTOMATION_COMMANDS for arg in args)


def main() -> int:
    args = tuple(sys.argv[1:])
    if not args or any(arg in _BANNED_COMMANDS for arg in args):
        raise SystemExit(_ERROR_MESSAGE)
    if _is_automation_invocation(args):
        setup_callable = _load_setup_callable()
        setup_callable()
        return 0
    raise SystemExit(_ERROR_MESSAGE)


if __name__ == "__main__":
    sys.exit(main())
