"""Runtime shims for optional pytest plugins and observability libraries."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable


def _ensure_repo_paths() -> None:
    repo_root = Path(__file__).resolve().parent
    src_path = repo_root / "src"
    for entry in (repo_root, src_path):
        entry_str = str(entry)
        if entry_str not in sys.path:
            sys.path.insert(0, entry_str)


_ensure_repo_paths()


def _module_from(source: ModuleType, name: str, *, extra: dict[str, object] | None = None) -> ModuleType:
    module = ModuleType(name)
    for attr, value in source.__dict__.items():
        if attr.startswith("__") and attr not in {"__all__", "__doc__"}:
            continue
        setattr(module, attr, value)
    if extra:
        for key, value in extra.items():
            setattr(module, key, value)
    module.__dict__.setdefault("__all__", [
        attr for attr in module.__dict__ if not attr.startswith("__")
    ])
    return module


def _install(name: str, factory: Callable[[], ModuleType]) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    module = factory()
    sys.modules[name] = module
    return module


def _install_pytest_timeout_stub() -> None:
    try:
        importlib.import_module("pytest_timeout")
    except ModuleNotFoundError:
        from tooling.plugins import timeout_stub

        stub = _module_from(timeout_stub, "pytest_timeout", extra={"STUB_ACTIVE": True})
        _install("pytest_timeout", lambda: stub)


def _install_xdist_stub() -> None:
    try:
        importlib.import_module("xdist.plugin")
        return
    except ModuleNotFoundError:
        pass
    from tooling.plugins import xdist_stub

    plugin_module = _module_from(xdist_stub, "xdist.plugin", extra={"STUB_ACTIVE": True})

    def build_xdist() -> ModuleType:
        base = ModuleType("xdist")
        base.plugin = plugin_module  # type: ignore[attr-defined]
        base.STUB_ACTIVE = True  # type: ignore[attr-defined]
        base.__all__ = ["plugin"]
        return base

    _install("xdist.plugin", lambda: plugin_module)
    _install("xdist", build_xdist)


def _install_pyside6_stub() -> None:
    try:
        importlib.import_module("PySide6.QtCore")
        importlib.import_module("PySide6.QtWidgets")
    except ModuleNotFoundError:
        from tooling.stubs import pyside6

        modules = pyside6.build_modules()
        for name, module in modules.items():
            _install(name, lambda module=module: module)


def _install_opentelemetry_stub() -> None:
    try:
        importlib.import_module("opentelemetry.trace")
    except ModuleNotFoundError:
        import sma._local_opentelemetry as local_ot

        _install("opentelemetry", lambda: local_ot)
        _install("opentelemetry.trace", lambda: local_ot.trace)


def _install_fakeredis_stub() -> None:
    try:
        importlib.import_module("fakeredis")
    except ModuleNotFoundError:
        import sma._local_fakeredis as local_fakeredis

        _install("fakeredis", lambda: _module_from(local_fakeredis, "fakeredis"))


_install_pytest_timeout_stub()
_install_xdist_stub()
_install_pyside6_stub()
_install_opentelemetry_stub()
_install_fakeredis_stub()

