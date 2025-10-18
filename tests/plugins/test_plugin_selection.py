from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_real_plugins_precede_stubs_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_root = tmp_path / "real_plugins"
    xdist_pkg = plugin_root / "xdist"
    timeout_pkg = plugin_root / "pytest_timeout"
    xdist_pkg.mkdir(parents=True)
    timeout_pkg.mkdir(parents=True)

    (xdist_pkg / "__init__.py").write_text(
        "FLAG = 'real-xdist'\n",
        encoding="utf-8",
    )
    (xdist_pkg / "plugin.py").write_text(
        "FLAG = 'real-xdist-plugin'\n",
        encoding="utf-8",
    )
    (timeout_pkg / "__init__.py").write_text(
        "FLAG = 'real-timeout'\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(plugin_root))

    to_purge = ["xdist", "xdist.plugin", "pytest_timeout"]
    removed = {name: sys.modules.pop(name, None) for name in to_purge}

    try:
        xdist_module = importlib.import_module("xdist")
        plugin_module = importlib.import_module("xdist.plugin")
        timeout_module = importlib.import_module("pytest_timeout")
    finally:
        for name, module in removed.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    debug_context = {
        "xdist_file": getattr(xdist_module, "__file__", ""),
        "plugin_file": getattr(plugin_module, "__file__", ""),
        "timeout_file": getattr(timeout_module, "__file__", ""),
        "sys_path_head": list(sys.path)[:3],
    }

    assert getattr(xdist_module, "FLAG", "") == "real-xdist", debug_context
    assert getattr(plugin_module, "FLAG", "") == "real-xdist-plugin", debug_context
    assert getattr(timeout_module, "FLAG", "") == "real-timeout", debug_context

    assert not getattr(xdist_module, "STUB_ACTIVE", False), debug_context
    assert not getattr(plugin_module, "STUB_ACTIVE", False), debug_context
    assert not getattr(timeout_module, "STUB_ACTIVE", False), debug_context


def test_real_plugins_precede_stubs_when_available_asyncio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_root = tmp_path / "wheel_like"
    asyncio_pkg = plugin_root / "pytest_asyncio"
    asyncio_pkg.mkdir(parents=True)

    module_path = asyncio_pkg / "__init__.py"
    module_path.write_text("FLAG = 'real-asyncio'\n", encoding="utf-8")

    import importlib.metadata as importlib_metadata
    from importlib.metadata import PackagePath

    class DummyDistribution:
        def __init__(self, base: Path) -> None:
            self._base = base
            self.files = [PackagePath("pytest_asyncio", "__init__.py")]

        def locate_file(self, path: PackagePath) -> Path:
            return self._base / Path(*path.parts)

    dummy_distribution = DummyDistribution(plugin_root)

    def fake_distributions():
        yield dummy_distribution

    monkeypatch.setattr(importlib_metadata, "distributions", fake_distributions)

    removed = {name: sys.modules.pop(name, None) for name in ("pytest_asyncio",)}
    try:
        module = importlib.import_module("pytest_asyncio")
    finally:
        for name, existing in removed.items():
            if existing is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = existing

    debug_context = {
        "asyncio_file": getattr(module, "__file__", ""),
        "stub_flag": getattr(module, "STUB_ACTIVE", None),
    }

    assert getattr(module, "FLAG", "") == "real-asyncio", debug_context
    assert not getattr(module, "STUB_ACTIVE", False), debug_context
