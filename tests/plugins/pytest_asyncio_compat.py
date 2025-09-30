"""Ensure pytest-asyncio is loaded with deterministic defaults in CI."""
from __future__ import annotations

import importlib
from typing import Any

from _pytest.config import Config
from _pytest.config.argparsing import Parser

_ASYNCIO_PLUGIN = "pytest_asyncio.plugin"


def _load_asyncio_module() -> Any:
    return importlib.import_module(_ASYNCIO_PLUGIN)


def pytest_load_initial_conftests(early_config: Config, parser: Parser, args: list[str]) -> None:
    module = _load_asyncio_module()
    pluginmanager = early_config.pluginmanager
    if not pluginmanager.has_plugin("pytest_asyncio"):
        module.pytest_addoption(parser, pluginmanager)
        pluginmanager.register(module, "pytest_asyncio")


def pytest_configure(config: Config) -> None:
    module = _load_asyncio_module()
    if not config.pluginmanager.has_plugin("pytest_asyncio"):
        config.pluginmanager.register(module, "pytest_asyncio")
    scope = config.getini("asyncio_default_fixture_loop_scope") or "function"
    config.inicfg.setdefault("asyncio_default_fixture_loop_scope", scope)
    if hasattr(config, "_inicache"):
        config._inicache["asyncio_default_fixture_loop_scope"] = scope  # type: ignore[attr-defined]
