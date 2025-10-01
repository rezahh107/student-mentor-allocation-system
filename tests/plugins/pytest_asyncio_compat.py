"""Ensure pytest-asyncio is loaded with deterministic defaults in CI."""
from __future__ import annotations

import importlib
from typing import Any

from _pytest.config import Config
from _pytest.config.argparsing import Parser

_ASYNCIO_PLUGIN = "pytest_asyncio.plugin"


def _load_asyncio_module() -> Any:
    return importlib.import_module(_ASYNCIO_PLUGIN)


def pytest_addoption(parser: Parser) -> None:
    parser.addini("asyncio_mode", "Default asyncio mode for pytest-asyncio", default="auto")


def pytest_load_initial_conftests(early_config: Config, parser: Parser, args: list[str]) -> None:
    module = _load_asyncio_module()
    pluginmanager = early_config.pluginmanager
    if not pluginmanager.has_plugin("pytest_asyncio"):
        module.pytest_addoption(parser, pluginmanager)
        pluginmanager.register(module, "pytest_asyncio")


def pytest_configure(config: Config) -> None:
    module = _load_asyncio_module()
    if not (
        config.pluginmanager.has_plugin("pytest_asyncio")
        or config.pluginmanager.has_plugin("pytest_asyncio.plugin")
    ):
        config.pluginmanager.register(module, "pytest_asyncio")
    try:
        mode = config.getini("asyncio_mode")
    except ValueError:
        mode = "auto"
    if not mode:
        mode = "auto"
    config.inicfg.setdefault("asyncio_mode", mode)
    if hasattr(config, "_inicache"):
        config._inicache["asyncio_mode"] = mode  # type: ignore[attr-defined]
    config.option.strict_config = True
    config.option.strict_markers = True
