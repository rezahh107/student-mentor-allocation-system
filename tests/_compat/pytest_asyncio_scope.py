"""Compatibility helpers to keep pytest-asyncio mode stable."""

from __future__ import annotations

from typing import Final

import pytest
from pytest import Config

_REQUIRED_MODE: Final[str] = "auto"


def pytest_configure(config: Config) -> None:
    """Ensure asyncio fixtures use auto mode without CLI flags."""
    stored = config.inicfg.get("asyncio_mode")
    if not stored:
        config.inicfg["asyncio_mode"] = _REQUIRED_MODE
    try:
        value = config.getini("asyncio_mode")
    except ValueError:
        config.inicfg["asyncio_mode"] = _REQUIRED_MODE
        return
    if value != _REQUIRED_MODE:
        raise pytest.UsageError(
            "asyncio_mode must be set to 'auto' for deterministic tests"
        )
