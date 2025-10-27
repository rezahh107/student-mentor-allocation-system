from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Iterable


def _purge_modules(names: Iterable[str]) -> dict[str, ModuleType | None]:
    removed: dict[str, ModuleType | None] = {}
    for name in names:
        removed[name] = sys.modules.pop(name, None)
    return removed


def _restore_modules(state: dict[str, ModuleType | None]) -> None:
    for name, module in state.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _reload_sitecustomize() -> ModuleType:
    module = importlib.import_module("sitecustomize")
    return importlib.reload(module)


def test_sitecustomize_registers_pytest_timeout_stub() -> None:
    removed = _purge_modules(["pytest_timeout"])
    try:
        _reload_sitecustomize()
        import pytest_timeout  # type: ignore

        debug_context = {
            "module": pytest_timeout,
            "dir": sorted(attr for attr in dir(pytest_timeout) if not attr.startswith("__")),
        }
        assert getattr(pytest_timeout, "STUB_ACTIVE", False), debug_context
    finally:
        _restore_modules(removed)
        _reload_sitecustomize()


def test_sitecustomize_registers_xdist_stub() -> None:
    removed = _purge_modules(["xdist", "xdist.plugin"])
    try:
        _reload_sitecustomize()
        import xdist  # type: ignore
        import xdist.plugin  # type: ignore

        debug_context = {
            "has_plugin": hasattr(xdist, "plugin"),
            "plugin_attrs": sorted(attr for attr in dir(xdist.plugin) if not attr.startswith("__")),
        }
        assert getattr(xdist.plugin, "STUB_ACTIVE", False), debug_context
        assert getattr(xdist, "STUB_ACTIVE", False), debug_context
    finally:
        _restore_modules(removed)
        _reload_sitecustomize()


def test_sitecustomize_registers_opentelemetry_stub() -> None:
    removed = _purge_modules(["opentelemetry", "opentelemetry.trace"])
    try:
        _reload_sitecustomize()
        import opentelemetry  # type: ignore
        from opentelemetry import trace  # type: ignore

        debug_context = {
            "module": opentelemetry,
            "trace_module": trace,
            "span_kind": getattr(trace, "SpanKind", None),
        }
        assert hasattr(trace, "SpanKind"), debug_context
    finally:
        _restore_modules(removed)
        _reload_sitecustomize()

