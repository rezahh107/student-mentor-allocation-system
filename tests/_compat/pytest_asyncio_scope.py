"""Compatibility helpers to keep pytest-asyncio loop scope stable."""

from __future__ import annotations

from typing import Final

import pytest
from pytest import Config

_REQUIRED_SCOPE: Final[str] = "function"


def pytest_configure(config: Config) -> None:
    """Ensure asyncio fixtures default to function scope without CLI flags."""
    stored = config.inicfg.get("asyncio_default_fixture_loop_scope")
    if not stored:
        config.inicfg["asyncio_default_fixture_loop_scope"] = _REQUIRED_SCOPE
    try:
        value = config.getini("asyncio_default_fixture_loop_scope")
    except ValueError:
        # pytest-asyncio plugin may be disabled; enforce our default manually.
        config.inicfg["asyncio_default_fixture_loop_scope"] = _REQUIRED_SCOPE
        return
    if value != _REQUIRED_SCOPE:
        raise pytest.UsageError(
            "asyncio_default_fixture_loop_scope must be set to 'function' for deterministic tests"
        )
