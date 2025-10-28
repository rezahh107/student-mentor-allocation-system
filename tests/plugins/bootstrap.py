"""Bootstrap critical pytest plugins when autoload is disabled."""
from __future__ import annotations

import sys

from _pytest.config import Config
from _pytest.config.argparsing import Parser

_REQUIRED = (
    "pytest_asyncio.plugin",
    "pytest_timeout",
    "xdist.plugin",
)


def _ensure_plugin(early_config: Config, parser: Parser, name: str) -> None:
    manager = early_config.pluginmanager
    base_name = name.split(".")[0]
    if manager.has_plugin(name) or manager.has_plugin(base_name):
        return
    module = sys.modules.get(name) or sys.modules.get(base_name)
    if module is not None:
        plugin_key = getattr(module, "__name__", name)
        if not manager.has_plugin(plugin_key):
            manager.register(module, plugin_key)
        return
    try:
        manager.import_plugin(name)
    except ImportError:
        # Allow missing optional plugins to fail silently; caller may handle.
        raise


def pytest_load_initial_conftests(early_config: Config, parser: Parser, args: list[str]) -> None:  # noqa: D401, ANN001
    del args
    for plugin_name in _REQUIRED:
        try:
            _ensure_plugin(early_config, parser, plugin_name)
        except ImportError:
            continue
    early_config.pluginmanager.import_plugin("tests.plugins.pytest_asyncio_compat")
