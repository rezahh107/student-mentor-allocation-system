from __future__ import annotations

import importlib
import sys
import types

import pytest

from repo_auditor_lite.compat.optional import OptionalDependencyError, optional_import


@pytest.fixture(autouse=True)
def reset_optional_cache():
    previous = {
        name: sys.modules.get(name)
        for name in ("requests", "yaml", "sqlalchemy", "httpx", "xlsxwriter")
    }
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_optional_import_returns_real_module_when_present(monkeypatch):
    fake_requests = types.ModuleType("requests")
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    loaded = optional_import("requests")
    assert loaded is fake_requests


def test_optional_import_returns_shim_when_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "requests", raising=False)
    loaded = optional_import("requests")
    assert loaded.__class__.__name__ == "_ShimModule"
    with pytest.raises(OptionalDependencyError) as excinfo:
        getattr(loaded, "get")
    message = str(excinfo.value)
    assert "کتابخانهٔ اختیاری requests" in message


def test_optional_import_reuses_cached_shim(monkeypatch):
    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    first = optional_import("yaml")
    second = optional_import("yaml")
    assert first is second


def test_optional_import_passthrough_for_non_optional_module():
    module = optional_import("json")
    assert module is importlib.import_module("json")
